# OneFlow 长期记忆工具
# 新增记忆前做冲突消解：对全部有效记忆做语义相似检索，相似度 > SIM_THRESHOLD 的旧记忆
# 交给 LLM 判定「补充/矛盾/重复」——矛盾→旧记忆标记 superseded；重复→跳过不存；补充→合并文本。
# embedding/LLM 任一失败都静默降级：记忆照常保存，功能不因外部依赖中断。
import asyncio
import concurrent.futures

from .registry import tool

# 余弦相似度超过该阈值才认为可能与旧记忆相关，交给 LLM 判定
SIM_THRESHOLD = 0.85

RELATION_SYSTEM = (
    "你是记忆管理员。判断两条用户记忆之间的关系，只输出一个词：重复/矛盾/补充。"
    "重复=两条说的是同一件事，新记忆没有带来新信息；"
    "矛盾=新记忆推翻了旧记忆（喜好/事实发生变化，两者不能并存）；"
    "补充=新记忆是旧记忆的延伸、细化或新增细节，两者可以并存。"
)


def _run_in_thread(fn):
    """在独立线程里跑同步包装的协程，避免在异步上下文中嵌套事件循环。"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn).result(timeout=20)


def _embed_text(text: str, cfg) -> str | None:
    """云端 embedding，失败静默降级为 None。"""
    from ..agent.embed import embed_text, embedding_to_json

    def _embed():
        return asyncio.run(embed_text(text, cfg))

    try:
        return embedding_to_json(_run_in_thread(_embed))
    except Exception:
        return None


async def _classify_relation(old_text: str, new_text: str, cfg) -> str | None:
    """LLM 判定新旧记忆关系：contradiction / duplicate / supplement；失败返回 None。"""
    from ..agent.llm import chat

    try:
        result = await chat(
            messages=[
                {"role": "system", "content": RELATION_SYSTEM},
                {"role": "user", "content": f"旧记忆：{old_text}\n新记忆：{new_text}"},
            ],
            tools=[],
            cfg=cfg,
        )
    except Exception:
        return None
    if result.error or not result.text:
        return None
    text = result.text.strip()
    for word, rel in (("矛盾", "contradiction"), ("重复", "duplicate"), ("补充", "supplement")):
        if word in text:
            return rel
    return None


def _classify_sync(old_text: str, new_text: str, cfg) -> str | None:
    def _run():
        return asyncio.run(_classify_relation(old_text, new_text, cfg))

    try:
        return _run_in_thread(_run)
    except Exception:
        return None


def _similar_memories(db, user_id: int, vector: list[float]) -> list:
    """语义检索该用户全部有效记忆，返回相似度 > SIM_THRESHOLD 的 [(记忆, 相似度)] 降序。"""
    from ..agent.embed import cosine, json_to_embedding
    from ..models import UserMemory

    rows = (
        db.query(UserMemory)
        .filter(UserMemory.user_id == user_id, UserMemory.status == "active")
        .all()
    )
    scored = []
    for m in rows:
        vec = json_to_embedding(m.embedding)
        if vec is not None:
            score = cosine(vector, vec)
            if score > SIM_THRESHOLD:
                scored.append((m, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


@tool(
    name="remember",
    description="记住一条关于用户的长期信息（偏好/事实/结论），供以后的问答复用；当用户透露值得长期记住的事实或偏好时调用",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string", "description": "要记住的内容，一句话"}},
        "required": ["text"],
    },
)
def remember(args, user, db, cfg=None):
    text = (args.get("text") or "").strip()
    if not text:
        return {"success": False, "error": "内容不能为空"}

    from ..models import UserMemory

    # 云端 embedding：失败静默降级为 None（记忆照常保存）
    embedding_json = _embed_text(text, cfg)

    # ── 冲突消解：先语义检索，高相似旧记忆交给 LLM 判定关系 ──
    from ..agent.embed import json_to_embedding

    vector = json_to_embedding(embedding_json)
    if vector is not None:
        similar = _similar_memories(db, user.id, vector)
        if similar:
            old, _score = similar[0]
            relation = _classify_sync(old.content, text, cfg)
            if relation == "duplicate":
                return {
                    "success": True, "action": "duplicate", "id": old.id,
                    "message": f"这条和之前的「{old.content}」是同一件事，已跳过保存",
                }
            if relation == "contradiction":
                old.status = "superseded"
                m = UserMemory(user_id=user.id, content=text, embedding=embedding_json)
                db.add(m)
                db.commit()
                db.refresh(m)
                return {
                    "success": True, "action": "superseded", "id": m.id, "content": m.content,
                    "message": f"你之前说过「{old.content}」，已更新为「{m.content}」",
                }
            if relation == "supplement":
                old.content = f"{old.content}；{text}"
                db.commit()
                return {
                    "success": True, "action": "merged", "id": old.id, "content": old.content,
                    "message": f"已补充进之前的记忆：「{old.content}」",
                }

    m = UserMemory(user_id=user.id, content=text, embedding=embedding_json)
    db.add(m)
    db.commit()
    db.refresh(m)
    return {"success": True, "action": "created", "id": m.id, "content": m.content}
