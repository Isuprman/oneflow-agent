# 习惯学习：统计近 N 天工具使用，高频行为主动建议沉淀为定时任务。
# 纯统计无 LLM 开销；已建议过的（UserSetting 标记）不重复打扰。
from datetime import datetime, timedelta

from ..models import Conversation, Notification, ToolCallLog, User, UserSetting

# 每日 21 点后跑一次行为洞察；近 N 天同一工具用满阈值次则主动建议
HABIT_INSIGHT_HOUR = 21
HABIT_WINDOW_DAYS = 7
HABIT_MIN_COUNT = 3
# 工具 → 建议文案（只洞察值得沉淀为习惯的工具）
HABIT_SUGGESTIONS = {
    "get_weather": "您最近经常查天气。需要的话对我说：每天早上8点播报天气，我可以每天主动向您报告。",
    "add_expense": "您最近经常记账。需要的话对我说：每天晚上9点汇总今日开支，我可以帮您每日盘点。",
    "schedule_event": "您最近经常安排日程。日程开始前我会自动提醒您，也可以让我每天早间简报今日安排。",
}


async def run(db, now: datetime) -> None:
    run_habit_insights(db, now)


def run_habit_insights(db, now: datetime) -> None:
    """习惯学习：统计近 N 天工具使用，高频行为主动建议沉淀为定时任务。

    纯统计无 LLM 开销；已建议过的（UserSetting 标记）不重复打扰。
    """
    today_key = now.strftime("%Y-%m-%d")
    window_start = now - timedelta(days=HABIT_WINDOW_DAYS)

    users = db.query(User).all()
    for user in users:
        flag = (
            db.query(UserSetting)
            .filter(UserSetting.user_id == user.id, UserSetting.key == "habit_last_check")
            .first()
        )
        if flag is not None and flag.value == today_key:
            continue

        # 该用户近 N 天的工具调用（经会话归属用户）
        rows = (
            db.query(ToolCallLog.tool_name)
            .join(Conversation, Conversation.id == ToolCallLog.conversation_id)
            .filter(Conversation.user_id == user.id, ToolCallLog.created_at >= window_start)
            .all()
        )
        counts: dict[str, int] = {}
        for (tool_name,) in rows:
            counts[tool_name] = counts.get(tool_name, 0) + 1

        for tool_name, count in counts.items():
            suggestion = HABIT_SUGGESTIONS.get(tool_name)
            if not suggestion or count < HABIT_MIN_COUNT:
                continue
            dedup_key = f"habit_suggested:{tool_name}"
            already = (
                db.query(UserSetting)
                .filter(UserSetting.user_id == user.id, UserSetting.key == dedup_key)
                .first()
            )
            if already is not None:
                continue
            db.add(Notification(user_id=user.id, title="习惯洞察", content=suggestion, kind="habit"))
            db.add(UserSetting(user_id=user.id, key=dedup_key, value=today_key))

        if flag is None:
            db.add(UserSetting(user_id=user.id, key="habit_last_check", value=today_key))
        else:
            flag.value = today_key
        db.commit()
