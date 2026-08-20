# OneFlow 定时任务管理路由 — 列表/启停/删除（晨间简报由专属开关管理，此处排除）
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import ScheduledTask, User
from ..scheduler import compute_next_run
from .briefing import BRIEFING_TITLE

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

KIND_LABELS = {"daily": "每天", "weekly": "每周", "once": "仅一次"}


class TaskOut(BaseModel):
    id: int
    title: str
    kind: str
    kind_label: str
    hour: int
    minute: int
    weekday: Optional[int] = None
    next_run_at: Optional[str] = None
    enabled: bool


class TaskUpdate(BaseModel):
    enabled: Optional[bool] = None
    hour: Optional[int] = None
    minute: Optional[int] = None


def _to_out(task: ScheduledTask) -> TaskOut:
    return TaskOut(
        id=task.id,
        title=task.title or "",
        kind=task.kind,
        kind_label=KIND_LABELS.get(task.kind, task.kind),
        hour=task.hour or 0,
        minute=task.minute or 0,
        weekday=task.weekday,
        next_run_at=task.next_run_at.isoformat() if task.next_run_at else None,
        enabled=bool(task.enabled),
    )


def _get_owned(db, task_id: int, user_id: int) -> ScheduledTask:
    task = (
        db.query(ScheduledTask)
        .filter(ScheduledTask.id == task_id, ScheduledTask.user_id == user_id)
        .first()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.title == BRIEFING_TITLE:
        raise HTTPException(status_code=400, detail="晨间简报请在专属开关处管理")
    return task


@router.get("", response_model=list[TaskOut])
def list_tasks(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(ScheduledTask)
        .filter(ScheduledTask.user_id == user.id, ScheduledTask.title != BRIEFING_TITLE)
        .order_by(ScheduledTask.next_run_at.asc())
        .all()
    )
    return [_to_out(t) for t in rows]


@router.put("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: int,
    body: TaskUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = _get_owned(db, task_id, user.id)

    if body.hour is not None:
        task.hour = max(0, min(23, body.hour))
    if body.minute is not None:
        task.minute = max(0, min(59, body.minute))

    if body.enabled is True:
        next_run = compute_next_run(
            task.kind, task.hour or 0, task.minute or 0, task.weekday, task.run_at, datetime.now()
        )
        if next_run is None:
            raise HTTPException(status_code=400, detail="一次性任务的时刻已过，无法重新启用")
        task.enabled = 1
        task.next_run_at = next_run
    elif body.enabled is False:
        task.enabled = 0
    elif task.enabled and (body.hour is not None or body.minute is not None):
        # 仅改时间：启用中的任务同步推进下次执行时刻
        task.next_run_at = compute_next_run(
            task.kind, task.hour or 0, task.minute or 0, task.weekday, task.run_at, datetime.now()
        )

    db.commit()
    db.refresh(task)
    return _to_out(task)


@router.delete("/{task_id}", status_code=204)
def delete_task(
    task_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = _get_owned(db, task_id, user.id)
    db.delete(task)
    db.commit()
