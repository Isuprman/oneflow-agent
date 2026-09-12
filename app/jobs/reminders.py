# 日程提醒：start_at 落在 [now-迟到宽限, now+提前窗口] 的未提醒日程推送通知。
# 已过期太久的不再补提醒（如服务停机错过窗口）。
from datetime import datetime, timedelta

from ..models import Notification, Schedule

# 日程提醒提前量：start_at 落在 [now, now+窗口] 内即推送提醒
REMINDER_WINDOW_MINUTES = 5
# 已过期太久的日程不再补提醒（如服务停机错过窗口）
REMINDER_LATE_MINUTES = 1


async def run(db, now: datetime) -> None:
    window_end = now + timedelta(minutes=REMINDER_WINDOW_MINUTES)
    late_limit = now - timedelta(minutes=REMINDER_LATE_MINUTES)
    events = (
        db.query(Schedule)
        .filter(
            Schedule.notified == 0,
            Schedule.start_at >= late_limit,
            Schedule.start_at <= window_end,
        )
        .all()
    )
    for event in events:
        db.add(
            Notification(
                user_id=event.user_id,
                title="日程提醒",
                content=f"{event.start_at:%H:%M} 您有日程：{event.title}",
                kind="reminder",
            )
        )
        event.notified = 1
    if events:
        db.commit()
