# OneFlow 长期记忆路由
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User, UserMemory
from ..schemas import MemoryOut, MemoryUpdate

router = APIRouter(prefix="/api/memories", tags=["memories"])


def _to_out(m: UserMemory) -> MemoryOut:
    return MemoryOut(id=m.id, content=m.content, created_at=m.created_at.isoformat())


@router.get("", response_model=List[MemoryOut])
def list_memories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mems = (
        db.query(UserMemory)
        .filter(UserMemory.user_id == current_user.id)
        .order_by(UserMemory.updated_at.desc())
        .all()
    )
    return [_to_out(m) for m in mems]


@router.put("/{memory_id}", response_model=MemoryOut)
def update_memory(
    memory_id: int,
    body: MemoryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """编辑一条记忆：更新文本并重嵌向量（无 embedding 配置时静默置空，退化为最近度召回）。"""
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="记忆内容不能为空")
    mem = (
        db.query(UserMemory)
        .filter(UserMemory.id == memory_id, UserMemory.user_id == current_user.id)
        .first()
    )
    if mem is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    mem.content = content
    from ..tools.memory import _embed_text
    from ..user_cfg import get_llm_cfg

    mem.embedding = _embed_text(content, get_llm_cfg(db, current_user.id))
    db.commit()
    db.refresh(mem)
    return _to_out(mem)


@router.delete("/{memory_id}", status_code=204)
def delete_memory(
    memory_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mem = (
        db.query(UserMemory)
        .filter(UserMemory.id == memory_id, UserMemory.user_id == current_user.id)
        .first()
    )
    if mem is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    db.delete(mem)
    db.commit()
