# OneFlow 用量路由 — 成本仪表盘：本月按场景汇总 + 月度摘要（v1 只做查询，不做主动推送）
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import TokenUsage, User

router = APIRouter(prefix="/api/usage", tags=["usage"])


def _month_bounds(today: datetime) -> tuple[datetime, datetime]:
    """本月自然月起止 [start, end)，UTC 口径。"""
    start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _by_scene_rows(db: Session, user_id: int, start: datetime, end: datetime) -> list[tuple]:
    """本月该用户按 scene 聚合的 (scene, prompt合计, completion合计)。"""
    return (
        db.query(
            TokenUsage.scene,
            func.coalesce(func.sum(TokenUsage.prompt_tokens), 0),
            func.coalesce(func.sum(TokenUsage.completion_tokens), 0),
        )
        .filter(
            TokenUsage.user_id == user_id,
            TokenUsage.created_at >= start,
            TokenUsage.created_at < end,
        )
        .group_by(TokenUsage.scene)
        .all()
    )


@router.get("/stats")
def usage_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """本月按场景汇总的 token 用量，成本仪表盘数据源。"""
    start, end = _month_bounds(datetime.now(timezone.utc))
    by_scene = [
        {"scene": scene, "prompt": int(prompt), "completion": int(completion)}
        for scene, prompt, completion in _by_scene_rows(db, current_user.id, start, end)
    ]
    by_scene.sort(key=lambda item: item["prompt"] + item["completion"], reverse=True)
    return {
        "total_prompt": sum(item["prompt"] for item in by_scene),
        "total_completion": sum(item["completion"] for item in by_scene),
        "by_scene": by_scene,
    }


@router.get("/monthly-summary")
def monthly_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """本月用量一句话摘要：前端通知中心/设置页轮询拉取即可，无需推送。"""
    start, end = _month_bounds(datetime.now(timezone.utc))
    rows = _by_scene_rows(db, current_user.id, start, end)
    total_prompt = sum(int(p) for _, p, _ in rows)
    total_completion = sum(int(c) for _, _, c in rows)
    total = total_prompt + total_completion
    return {
        "month": f"{start.year}-{start.month:02d}",
        "total_prompt": total_prompt,
        "total_completion": total_completion,
        "total_tokens": total,
        "summary": f"本月已用 {total} tokens（输入 {total_prompt} / 输出 {total_completion}）",
    }
