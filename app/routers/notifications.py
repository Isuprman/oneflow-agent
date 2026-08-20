# OneFlow 主动通知路由 — 定时任务播报/日程提醒，前端轮询拉取
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Notification, User
from ..schemas import NotificationOut

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _to_out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        title=n.title,
        content=n.content,
        kind=n.kind or "task",
        created_at=n.created_at.isoformat(),
    )


@router.get("", response_model=List[NotificationOut])
def list_notifications(
    unread_only: bool = Query(default=True, alias="unread"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """拉取通知（默认仅未读），最新在前，最多 20 条。"""
    query = db.query(Notification).filter(Notification.user_id == current_user.id)
    if unread_only:
        query = query.filter(Notification.read == 0)
    rows = query.order_by(Notification.id.desc()).limit(20).all()
    return [_to_out(n) for n in rows]


@router.post("/{notification_id}/read", status_code=204)
def mark_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    note = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == current_user.id)
        .first()
    )
    if note is None:
        raise HTTPException(status_code=404, detail="通知不存在")
    note.read = 1
    db.commit()


@router.delete("/{notification_id}", status_code=204)
def delete_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除一条通知（通知中心用）；不存在或不属于当前用户返回 404。"""
    note = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == current_user.id)
        .first()
    )
    if note is None:
        raise HTTPException(status_code=404, detail="通知不存在")
    db.delete(note)
    db.commit()
