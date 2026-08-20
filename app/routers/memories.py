# OneFlow 长期记忆路由
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User, UserMemory
from ..schemas import MemoryOut

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
