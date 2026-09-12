# OneFlow 后台调度引擎 — 单一 30s 轮询 tick：到期任务跑 agent 主动播报 + 遍历后台职责注册表。
# 设计：每 30s 一个轮询 job（而非每任务一个 cron job），任务增删无需重挂 job，重启即自愈；
# 各主动服务（提醒/关怀/洞察/分身/面试/体检…）在 app/jobs/ 各自成模块，加新职责不改 tick。
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .db import SessionLocal
from .jobs import REGISTRY
from .models import Conversation, Notification, ScheduledTask, User

# 轮询间隔（秒）：决定定时任务/提醒的触发精度
TICK_SECONDS = 30
# 定时任务在用户专属播报会话中执行，标题固定便于复用
TASK_CONVERSATION_TITLE = "定时播报"


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
    """单次轮询：执行到期定时任务 + 遍历后台职责注册表。独立 DB 会话，异常不扩散。"""
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

        # 各后台职责：单块失败不拖垮其他规则，异常当天自报一次
        for job in REGISTRY:
            if job.hour_gate is not None and now.hour < job.hour_gate:
                continue
            try:
                await job.run(db, now)
            except Exception as e:
                db.rollback()
                notify_system_error(db, f"{job.label}失败（{e}）")
    finally:
        db.close()


# 兼容导出：历史调用方与测试直接从 app.scheduler 导入这两个规则函数
from .jobs.care import run_care_rules  # noqa: E402,F401
from .jobs.habits import run_habit_insights  # noqa: E402,F401


def start_scheduler() -> AsyncIOScheduler:
    """启动调度器（FastAPI lifespan 调用）。"""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(tick, "interval", seconds=TICK_SECONDS, id="oneflow_tick")
    scheduler.start()
    return scheduler


def shutdown_scheduler(scheduler: AsyncIOScheduler) -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
