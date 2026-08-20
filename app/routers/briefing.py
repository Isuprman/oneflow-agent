# OneFlow 晨间简报 — 一键预置的每日简报任务（天气+日程，到点主动播报）
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import ScheduledTask, User
from ..scheduler import compute_next_run

router = APIRouter(prefix="/api/briefing", tags=["briefing"])

# 预置任务的固定标题（作为同一用户下"晨间简报"的唯一键）
BRIEFING_TITLE = "晨间简报"
# 到点后交给 agent 的指令：先天气后日程，合成简短播报
BRIEFING_INSTRUCTION = (
    "这是用户的每日晨间简报任务：请先用 get_weather 查询用户常用城市今天的天气"
    "（若长期记忆里不知道用户城市，则默认查询上海），再用 list_schedule 查询今天的日程，"
    "最后用两三句简洁中文合成一段早间播报：先天气、后日程；没有日程就说今天暂无安排。"
)


class BriefingIn(BaseModel):
    enabled: bool
    hour: int = 8
    minute: int = 0


class BriefingOut(BaseModel):
    enabled: bool
    hour: int
    minute: int


def _find(db, user_id: int):
    return (
        db.query(ScheduledTask)
        .filter(ScheduledTask.user_id == user_id, ScheduledTask.title == BRIEFING_TITLE)
        .first()
    )


@router.get("", response_model=BriefingOut)
def get_briefing(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = _find(db, user.id)
    if task is None or not task.enabled:
        return BriefingOut(enabled=False, hour=task.hour if task else 8, minute=task.minute if task else 0)
    return BriefingOut(enabled=True, hour=task.hour or 8, minute=task.minute or 0)


@router.put("", response_model=BriefingOut)
def save_briefing(
    body: BriefingIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    hour = max(0, min(23, body.hour))
    minute = max(0, min(59, body.minute))
    task = _find(db, user.id)

    if not body.enabled:
        if task is not None:
            task.enabled = 0
            db.commit()
        return BriefingOut(enabled=False, hour=hour, minute=minute)

    now = datetime.now()
    next_run_at = compute_next_run("daily", hour, minute, None, None, now)
    if task is None:
        task = ScheduledTask(
            user_id=user.id,
            title=BRIEFING_TITLE,
            instruction=BRIEFING_INSTRUCTION,
            kind="daily",
            hour=hour,
            minute=minute,
            enabled=1,
            next_run_at=next_run_at,
        )
        db.add(task)
    else:
        task.hour = hour
        task.minute = minute
        task.enabled = 1
        task.next_run_at = next_run_at
    db.commit()
    return BriefingOut(enabled=True, hour=hour, minute=minute)
