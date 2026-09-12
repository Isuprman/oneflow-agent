# 情景关怀：明天有雨雪且明天有日程 → 前一晚主动提醒带伞/提前出发。
# 纯规则无 LLM 开销；天气查询失败静默跳过，每人每天最多一次。
from datetime import datetime, timedelta

from ..models import Notification, Schedule, User, UserSetting

# 每晚 20 点后检查：明天有雨/雪 × 明天有日程 → 前一晚主动提醒
CARE_HOUR = 20
CARE_PRECIP_THRESHOLD = 60  # 降水概率阈值
CARE_BAD_WEATHER = ("雨", "毛毛雨", "阵雨", "雷暴", "雪")
CARE_DEFAULT_CITY = "上海"


async def run(db, now: datetime) -> None:
    run_care_rules(db, now)


def run_care_rules(db, now: datetime) -> None:
    """情景关怀：明天有雨雪且明天有日程 → 前一晚主动提醒带伞/提前出发。

    纯规则无 LLM 开销；天气查询失败静默跳过，每人每天最多一次。
    """
    from ..tools.profile import load_profile
    from ..tools.weather import query_weather

    today_key = now.strftime("%Y-%m-%d")
    tomorrow = now + timedelta(days=1)
    tomorrow_key = tomorrow.strftime("%Y-%m-%d")

    users = db.query(User).all()
    for user in users:
        flag = (
            db.query(UserSetting)
            .filter(UserSetting.user_id == user.id, UserSetting.key == "care_last_check")
            .first()
        )
        if flag is not None and flag.value == today_key:
            continue

        city = load_profile(db, user.id).get("city") or CARE_DEFAULT_CITY
        try:
            weather = query_weather(city, tomorrow_key)
        except Exception:
            weather = {"success": False}
        if weather.get("success"):
            bad = weather.get("weather") in CARE_BAD_WEATHER
            wet = (weather.get("precip_prob") or 0) >= CARE_PRECIP_THRESHOLD
            if bad or wet:
                events = (
                    db.query(Schedule)
                    .filter(
                        Schedule.user_id == user.id,
                        Schedule.start_at >= datetime(tomorrow.year, tomorrow.month, tomorrow.day),
                        Schedule.start_at < datetime(tomorrow.year, tomorrow.month, tomorrow.day) + timedelta(days=1),
                    )
                    .order_by(Schedule.start_at.asc())
                    .all()
                )
                if events:
                    first = events[0]
                    agenda = f"您明天 {first.start_at:%H:%M} 有「{first.title}」" + (
                        f"等 {len(events)} 个日程" if len(events) > 1 else ""
                    )
                    content = (
                        f"先生，{city}明天预报有{weather.get('weather')}"
                        f"（降水概率 {weather.get('precip_prob')}%）。{agenda}，建议带伞并提前出发。"
                    )
                    db.add(Notification(user_id=user.id, title="明日天气关怀", content=content, kind="care"))

        if flag is None:
            db.add(UserSetting(user_id=user.id, key="care_last_check", value=today_key))
        else:
            flag.value = today_key
        db.commit()
