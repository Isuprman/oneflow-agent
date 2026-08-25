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

# ---- 情景关怀 ----
# 每晚 20 点后检查：明天有雨/雪 × 明天有日程 → 前一晚主动提醒
CARE_HOUR = 20
CARE_PRECIP_THRESHOLD = 60  # 降水概率阈值
CARE_BAD_WEATHER = ("雨", "毛毛雨", "阵雨", "雷暴", "雪")
CARE_DEFAULT_CITY = "上海"


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
    失败分类：LLM 类错误转人话并标 system_error（前端只展示不播报），其余照常播报。
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

    friendly = _friendly_llm_error(reply)
    if friendly is not None:
        content = f"先生，定时任务「{task.title or '未命名'}」未能完成：{friendly}"
        kind = "system_error"
    else:
        content = reply
        kind = "task"
    db.add(
        Notification(
            user_id=user.id,
            title=task.title or "定时任务",
            content=content,
            kind=kind,
        )
    )
    db.commit()


def _friendly_llm_error(reply: str) -> str | None:
    """识别 LLM 类失败并转成可操作的人话；非 LLM 错误返回 None。"""
    if not reply:
        return None
    if reply.startswith("LLM 调用出错"):
        return "模型服务暂时不可用（可能是密钥失效或网络异常），请在设置页检查 LLM 配置。"
    if "LLM 未配置" in reply:
        return "尚未配置 LLM 密钥，请在设置页填写后重试。"
    return None


def notify_system_error(db, message: str) -> None:
    """系统异常通知：每天最多一条，避免持续出错时刷屏。

    注意：模型 created_at 存的是 UTC（models.now），比较基准也用 UTC 零点。
    """
    utc_day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    already = (
        db.query(Notification)
        .filter(Notification.kind == "system_error", Notification.created_at >= utc_day_start)
        .count()
    )
    if already > 0:
        return
    # 系统级错误无明确归属用户：发给全部用户（单人部署场景下即本人）
    for user in db.query(User).all():
        db.add(
            Notification(
                user_id=user.id,
                title="系统自检",
                content=f"先生，后台服务出现异常：{message}",
                kind="system_error",
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
        try:
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
        except Exception as e:  # 单块失败不拖垮其他规则，异常当天自报一次
            db.rollback()
            notify_system_error(db, f"日程提醒检查失败（{e}）")

        # 每晚 20 点后：情景关怀（每人每天一次）；21 点后：习惯洞察
        if now.hour >= CARE_HOUR:
            try:
                run_care_rules(db, now)
            except Exception as e:
                db.rollback()
                notify_system_error(db, f"情景关怀检查失败（{e}）")
        if now.hour >= HABIT_INSIGHT_HOUR:
            try:
                run_habit_insights(db, now)
            except Exception as e:
                db.rollback()
                notify_system_error(db, f"习惯洞察失败（{e}）")
            # 21 点后顺带：习惯 → 技能提案（经验结晶，走既有审批流）
            try:
                import asyncio

                from .learn.habit import run_daily_proposals

                asyncio.run(run_daily_proposals(db))
            except Exception as e:
                db.rollback()
                notify_system_error(db, f"习惯提案生成失败（{e}）")
            # 21 点后顺带：上线技能质量反馈环（差评自动降级 / 好评一次性通知）
            try:
                import asyncio

                from .learn.habit import run_skill_quality_check

                asyncio.run(run_skill_quality_check(db))
            except Exception as e:
                db.rollback()
                notify_system_error(db, f"技能质量检查失败（{e}）")
    finally:
        db.close()


def run_care_rules(db, now: datetime) -> None:
    """情景关怀：明天有雨雪且明天有日程 → 前一晚主动提醒带伞/提前出发。

    纯规则无 LLM 开销；天气查询失败静默跳过，每人每天最多一次。
    """
    from .tools.profile import load_profile
    from .tools.weather import query_weather

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
