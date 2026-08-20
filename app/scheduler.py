# OneFlow 后台调度引擎 — 定时任务到点跑 agent 主动播报 + 日程到期提醒
# 设计：单一 30s 轮询 job（而非每任务一个 cron job），任务增删无需重挂 job，重启即自愈。
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .db import SessionLocal
from .models import Conversation, Notification, Schedule, ScheduledTask, ToolCallLog, User, UserSetting

# 轮询间隔（秒）：决定定时任务/提醒的触发精度
TICK_SECONDS = 30
# 日程提醒提前量：start_at 落在 [now, now+窗口] 内即推送提醒
REMINDER_WINDOW_MINUTES = 5
# 已过期太久的日程不再补提醒（如服务停机错过窗口）
REMINDER_LATE_MINUTES = 1
# 定时任务在用户专属播报会话中执行，标题固定便于复用
TASK_CONVERSATION_TITLE = "定时播报"

# ---- 习惯学习 ----
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


def compute_next_run(
    kind: str,
    hour: int,
    minute: int,
    weekday: int | None,
    run_at: datetime | None,
    now: datetime,
) -> datetime | None:
    """计算任务下一次执行时刻（纯函数，便于测试）。

    - once：直接用 run_at（已过则返回 None 表示不再执行）
    - daily：今天/明天的 hour:minute
    - weekly：最近一个 weekday 的 hour:minute（weekday: 1=周一…7=周日）
    """
    if kind == "once":
        if run_at is None or run_at <= now:
            return None
        return run_at
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if kind == "daily":
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate
    if kind == "weekly":
        target = (weekday or 1) - 1  # 转成 Python weekday：0=周一
        days_ahead = (target - now.weekday()) % 7
        candidate += timedelta(days=days_ahead)
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate
    return None


async def _execute_task(db, task: ScheduledTask) -> None:
    """执行一条到期任务：在用户的「定时播报」会话里跑 agent，产出通知。

    调用前 tick 已推进 next_run_at/enabled，此处只管执行与播报。
    """
    from .agent.engine import run_agent

    user = db.get(User, task.user_id)
    if user is None:
        return

    conv = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id, Conversation.title == TASK_CONVERSATION_TITLE)
        .first()
    )
    if conv is None:
        conv = Conversation(user_id=user.id, title=TASK_CONVERSATION_TITLE)
        db.add(conv)
        db.commit()
        db.refresh(conv)

    try:
        reply, _steps, _trace = await run_agent(db, user, conv.id, task.instruction)
    except Exception as e:  # 任务失败也要告知用户，而不是静默吞掉
        reply = f"定时任务执行失败: {e}"

    db.add(
        Notification(
            user_id=user.id,
            title=task.title or "定时任务",
            content=reply,
            kind="task",
        )
    )
    db.commit()


async def tick() -> None:
    """单次轮询：执行到期定时任务 + 推送临期日程提醒。独立 DB 会话，异常不扩散。"""
    db = SessionLocal()
    try:
        now = datetime.now()

        tasks = (
            db.query(ScheduledTask)
            .filter(
                ScheduledTask.enabled == 1,
                ScheduledTask.next_run_at.isnot(None),
                ScheduledTask.next_run_at <= now,
            )
            .all()
        )
        for task in tasks:
            # 先推进 next_run_at 再执行，防止长任务执行期间被重复捞起
            if task.kind == "once":
                task.enabled = 0
                task.next_run_at = None
            else:
                task.next_run_at = compute_next_run(
                    task.kind, task.hour or 0, task.minute or 0, task.weekday, None, now
                )
            db.commit()
            await _execute_task(db, task)

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

        # 每晚 21 点后：每人每天跑一次习惯洞察
        if now.hour >= HABIT_INSIGHT_HOUR:
            run_habit_insights(db, now)
    finally:
        db.close()


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


def start_scheduler() -> AsyncIOScheduler:
    """启动调度器（FastAPI lifespan 调用）。"""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(tick, "interval", seconds=TICK_SECONDS, id="oneflow_tick")
    scheduler.start()
    return scheduler


def shutdown_scheduler(scheduler: AsyncIOScheduler) -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
