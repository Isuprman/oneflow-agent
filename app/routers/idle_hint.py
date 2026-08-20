# OneFlow 闲置轻推 — 贾维斯长时间没被理睬时主动搭话
# 纯规则零 LLM：按价值排序选话题（待确认操作 → 临期日程 → 今日天气 → 深夜问候），
# 前端负责闲置判定与频控（每会话最多 2 次），后端只负责给出"值得说的话题"或 null。
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import PendingAction, Schedule, User, UserSetting
from ..tools.profile import load_profile

router = APIRouter(prefix="/api/idle-hint", tags=["idle"])

DEFAULT_CITY = "上海"


class IdleHint(BaseModel):
    topic: Optional[str] = None
    text: Optional[str] = None


def _get_flag(db, user_id: int, key: str) -> Optional[str]:
    row = (
        db.query(UserSetting)
        .filter(UserSetting.user_id == user_id, UserSetting.key == key)
        .first()
    )
    return row.value if row else None


def _set_flag(db, user_id: int, key: str, value: str) -> None:
    row = (
        db.query(UserSetting)
        .filter(UserSetting.user_id == user_id, UserSetting.key == key)
        .first()
    )
    if row is None:
        db.add(UserSetting(user_id=user_id, key=key, value=value))
    else:
        row.value = value
    db.commit()


@router.get("", response_model=IdleHint)
def get_idle_hint(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = datetime.now()

    # 1) 有待确认的高危操作：最有行动价值
    pending = db.query(PendingAction).filter(PendingAction.user_id == user.id).first()
    if pending is not None:
        return IdleHint(
            topic="confirm",
            text=f"先生，{pending.summary}。您只需回复“确认”或“取消”。",
        )

    # 2) 未来 60 分钟内有日程
    soon = (
        db.query(Schedule)
        .filter(
            Schedule.user_id == user.id,
            Schedule.start_at > now,
            Schedule.start_at <= now + timedelta(minutes=60),
        )
        .order_by(Schedule.start_at.asc())
        .first()
    )
    if soon is not None:
        minutes = max(1, int((soon.start_at - now).total_seconds() // 60))
        return IdleHint(
            topic="agenda",
            text=f"先生，{soon.start_at:%H:%M} 您有「{soon.title}」，还有约 {minutes} 分钟开始。",
        )

    # 3) 今日天气异常（每天最多查一次，避免频繁打天气 API）
    today_key = now.strftime("%Y-%m-%d")
    if _get_flag(db, user.id, "idle_weather_day") != today_key:
        city = load_profile(db, user.id).get("city") or DEFAULT_CITY
        try:
            from ..tools.weather import query_weather

            weather = query_weather(city, today_key)
            if weather.get("success") and weather.get("weather") in ("雨", "毛毛雨", "阵雨", "雷暴", "雪"):
                _set_flag(db, user.id, "idle_weather_day", today_key)
                return IdleHint(
                    topic="weather",
                    text=f"先生，{city}今天有{weather.get('weather')}，出门记得带伞。",
                )
        except Exception:
            pass  # 天气查不到就安静，不打扰
        _set_flag(db, user.id, "idle_weather_day", today_key)

    # 4) 深夜兜底问候（前端限制每会话最多一次）
    if now.hour >= 22 or now.hour < 5:
        return IdleHint(topic="night", text="夜深了，先生。若无其他吩咐，早些休息。")

    return IdleHint(topic=None, text=None)
