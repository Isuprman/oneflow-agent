# RAG 知识库路由 — 上传 / 列表 / 删除
# 上传为首个 multipart 端点：python-multipart 已在 requirements；处理走 BackgroundTasks。
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import KnowledgeChunk, KnowledgeDoc, User
from ..tools.knowledge import process_document
from ..user_cfg import get_llm_cfg

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

ALLOWED_EXT = (".txt", ".md", ".pdf")
MAX_SIZE = 10 * 1024 * 1024  # 10MB


class KnowledgeDocOut(BaseModel):
    id: int
    filename: str
    status: str
    error: Optional[str] = None
    size: int
    chunk_count: int
    created_at: Optional[str] = None


def _to_out(doc: KnowledgeDoc) -> KnowledgeDocOut:
    return KnowledgeDocOut(
        id=doc.id,
        filename=doc.filename,
        status=doc.status,
        error=doc.error,
        size=doc.size,
        chunk_count=doc.chunk_count,
        created_at=doc.created_at.isoformat() if doc.created_at else None,
    )


@router.post("", response_model=KnowledgeDocOut)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传文档建 knowledge_doc（pending），响应后由后台任务切块 embedding。"""
    filename = file.filename or ""
    if not filename.lower().endswith(ALLOWED_EXT):
        raise HTTPException(status_code=400, detail="仅支持 txt / md / pdf 文件")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="文件超过 10MB 上限，请拆分后上传")

    doc = KnowledgeDoc(user_id=current_user.id, filename=filename, status="pending", size=len(data))
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # cfg 在请求内取好（后台任务里不再开会话取用户配置）
    cfg = get_llm_cfg(db, current_user.id)
    background.add_task(process_document, doc.id, filename, data, cfg)
    return _to_out(doc)


@router.get("", response_model=List[KnowledgeDocOut])
def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    docs = (
        db.query(KnowledgeDoc)
        .filter(KnowledgeDoc.user_id == current_user.id)
        .order_by(KnowledgeDoc.id.desc())
        .all()
    )
    return [_to_out(doc) for doc in docs]


@router.delete("/{doc_id}", status_code=204)
def delete_document(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = (
        db.query(KnowledgeDoc)
        .filter(KnowledgeDoc.id == doc_id, KnowledgeDoc.user_id == current_user.id)
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    # 显式连块删（SQLite 未开 FK pragma，靠应用层保证）
    db.query(KnowledgeChunk).filter(KnowledgeChunk.doc_id == doc.id).delete()
    db.delete(doc)
    db.commit()
