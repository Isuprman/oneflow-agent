# RAG 知识库 — 文档切块 embedding 与语义检索工具
#
# 上传（routers/knowledge.py）→ process_document 后台切块逐块 embedding → search_knowledge 召回。
# 与长期记忆不同：知识不做时间衰减（文档不会「忘」），召回纯按余弦相似度。
import asyncio
import concurrent.futures
import io

from ..models import KnowledgeChunk, KnowledgeDoc
from .registry import tool

# 切块参数：约 600 字符一块（中文 ~1 字/token），相邻块 100 字符重叠防语义截断
CHUNK_MAX_CHARS = 600
CHUNK_OVERLAP = 100
# 单文档块数上限：防止超大文档把 embedding 调用拖到失控
MAX_CHUNKS = 300
# 召回条数
TOP_K = 5


def _run_in_thread(fn):
    """在独立线程里跑同步包装的协程，避免在异步上下文中嵌套事件循环。"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn).result(timeout=60)


def _embed_json(text: str, cfg) -> str | None:
    """单块文本 → JSON 向量；失败静默返回 None（与记忆 embedding 同一降级语义）。"""
    from ..agent.embed import embed_text, embedding_to_json

    def _embed():
        return asyncio.run(embed_text(text, cfg))

    try:
        return embedding_to_json(_run_in_thread(_embed))
    except Exception:
        return None


def extract_text(filename: str, data: bytes) -> str:
    """按扩展名提取纯文本：txt/md 直接解码（utf-8 失败回退 gbk），pdf 用 pypdf。"""
    lower = (filename or "").lower()
    if lower.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "".join((page.extract_text() or "") for page in reader.pages)
        if len(text.strip()) < 20:
            raise ValueError("未能从 PDF 提取到文本——可能是扫描件（无文字层），请换文字版或拆分上传")
        return text
    if lower.endswith(".txt") or lower.endswith(".md"):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("gbk", errors="ignore")
    raise ValueError("仅支持 txt / md / pdf 文件")


def chunk_text(text: str, max_chars: int = CHUNK_MAX_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """按空行切段聚合到 max_chars；超长段落硬切（带 overlap）。返回块列表，上限 MAX_CHUNKS。"""
    paragraphs = [p.strip() for p in (text or "").replace("\r\n", "\n").split("\n\n") if p.strip()]
    # 无空行的纯文本：按单行聚合
    if not paragraphs:
        paragraphs = [line.strip() for line in (text or "").splitlines() if line.strip()]

    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if len(para) > max_chars:
            # 超长段落先冲刷缓冲，再硬切
            if buf:
                chunks.append(buf)
                buf = ""
            step = max_chars - overlap
            for start in range(0, len(para), step):
                piece = para[start : start + max_chars]
                chunks.append(piece)
                if start + max_chars >= len(para):
                    break
            continue
        if len(buf) + len(para) + 1 > max_chars and buf:
            chunks.append(buf)
            buf = para
        else:
            buf = f"{buf}\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return [c.strip() for c in chunks if c.strip()][:MAX_CHUNKS]


def process_document(doc_id: int, filename: str, data: bytes, cfg: dict) -> None:
    """后台处理：提取 → 切块 → 逐块 embedding → 置 ready；失败置 failed + 原因。

    使用独立 DB 会话（BackgroundTask 在响应结束后运行，请求会话已关闭）。
    """
    from ..db import SessionLocal
    from ..agent.embed import embedding_to_json

    db = SessionLocal()
    try:
        doc = db.query(KnowledgeDoc).filter(KnowledgeDoc.id == doc_id).first()
        if doc is None:
            return
        try:
            text = extract_text(filename, data)
            chunks = chunk_text(text)
            if not chunks:
                raise ValueError("文档内容为空")
            db.query(KnowledgeChunk).filter(KnowledgeChunk.doc_id == doc_id).delete()
            for idx, chunk in enumerate(chunks):
                db.add(
                    KnowledgeChunk(
                        user_id=doc.user_id,
                        doc_id=doc_id,
                        idx=idx,
                        content=chunk,
                        embedding=embedding_to_json(_embed_vector(chunk, cfg)),
                    )
                )
            doc.status = "ready"
            doc.chunk_count = len(chunks)
            doc.error = None
        except Exception as e:  # 任何失败都落状态而非让文档永远 pending
            db.rollback()
            doc = db.query(KnowledgeDoc).filter(KnowledgeDoc.id == doc_id).first()
            if doc is not None:
                doc.status = "failed"
                doc.error = str(e)[:500]
        db.commit()
    finally:
        db.close()


def _embed_vector(text: str, cfg) -> list[float] | None:
    """块文本 → 向量（None 表示 embedding 不可用，块仍保存但不参与语义召回）。"""
    from ..agent.embed import embed_text

    def _embed():
        return asyncio.run(embed_text(text, cfg))

    try:
        return _run_in_thread(_embed)
    except Exception:
        return None


@tool(
    name="search_knowledge",
    description=(
        "在用户上传的文档知识库中检索相关内容（个人笔记/资料/说明书等）。"
        "当用户提问可能与其上传过的文档有关，或需要引用文档细节时调用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索关键词或问题"},
        },
        "required": ["query"],
    },
)
def search_knowledge(args: dict, user, db, cfg=None):
    """语义召回 top5：带文件名与相似度分数返回，供 agent 引用作答。"""
    query = (args.get("query") or "").strip()
    if not query:
        return {"success": False, "error": "检索词不能为空"}
    from ..agent.embed import cosine, embed_text, json_to_embedding

    def _embed():
        return asyncio.run(embed_text(query, cfg))

    try:
        query_vec = _run_in_thread(_embed)
    except Exception:
        query_vec = None
    if query_vec is None:
        return {"success": False, "error": "知识库检索需要 embedding 能力（OpenAI 或云端 Qwen 密钥），当前不可用"}

    rows = (
        db.query(KnowledgeChunk, KnowledgeDoc.filename)
        .join(KnowledgeDoc, KnowledgeDoc.id == KnowledgeChunk.doc_id)
        .filter(
            KnowledgeChunk.user_id == user.id,
            KnowledgeDoc.status == "ready",
            KnowledgeChunk.embedding.isnot(None),
        )
        .all()
    )
    scored = []
    for chunk, filename in rows:
        vec = json_to_embedding(chunk.embedding)
        if vec is None:
            continue
        scored.append((cosine(query_vec, vec), chunk, filename))
    scored.sort(key=lambda x: x[0], reverse=True)
    return {
        "success": True,
        "results": [
            {"file": filename, "snippet": chunk.content[:400], "score": round(score, 3)}
            for score, chunk, filename in scored[:TOP_K]
        ],
    }
