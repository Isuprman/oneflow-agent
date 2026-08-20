# 定时任务工具 — 让 Agent 把"每天/每周/某时刻"的指令沉淀为后台任务，到点自动执行并播报
from datetime import datetime, timedelta

from .registry import tool


def _parse_once_datetime(date: str, hour: int, minute: int) -> datetime | None:
    """解析 once 任务的时刻：date 支持 YYYY-MM-DD / 明天 / 后天 / 今天。"""
    today = datetime.now().date()
    if date in ("今天", "today", ""):
        target = today
    elif date in ("明天", "tomorrow"):
        target = today + timedelta(days=1)
    elif date in ("后天",):
        target = today + timedelta(days=2)
    else:
        try:
            target = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return None
    return datetime(target.year, target.month, target.day, hour, minute)


@tool(
    name="create_scheduled_task",
    description="创建定时任务：到点后系统会自动执行 instruction 描述的指令（可自动调用天气/日程等工具）并向用户主动播报。"
    "用户说'每天早上8点播报天气''每周五17点提醒我交周报''明天下午3点提醒我开会'时使用。",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "任务简短标题，如'早间播报'"},
            "instruction": {"type": "string", "description": "到点要执行的完整指令，如'查询上海今天天气并简要播报'"},
            "kind": {"type": "string", "enum": ["daily", "weekly", "once"], "description": "daily=每天 weekly=每周 once=仅一次"},
            "hour": {"type": "integer", "description": "执行小时（24小时制，0-23）"},
            "minute": {"type": "integer", "description": "执行分钟（0-59），默认0"},
            "weekday": {"type": "integer", "description": "weekly 必填：1=周一…7=周日"},
            "date": {"type": "string", "description": "once 必填：YYYY-MM-DD 或 今天/明天/后天"},
        },
        "required": ["title", "instruction", "kind", "hour"],
    },
)
def create_scheduled_task(args, user, db):
    from ..models import ScheduledTask
    from ..scheduler import compute_next_run

    title = (args.get("title") or "").strip()
    instruction = (args.get("instruction") or "").strip()
    kind = args.get("kind")
    if not title or not instruction:
        return {"success": False, "error": "title 和 instruction 不能为空"}
    if kind not in ("daily", "weekly", "once"):
        return {"success": False, "error": "kind 必须是 daily/weekly/once"}

    hour = int(args.get("hour", 8))
    minute = int(args.get("minute") or 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return {"success": False, "error": "时间不合法：hour 0-23，minute 0-59"}

    weekday = args.get("weekday")
    run_at = None
    if kind == "weekly":
        if weekday is None or not (1 <= int(weekday) <= 7):
            return {"success": False, "error": "weekly 任务必须给 weekday（1=周一…7=周日）"}
        weekday = int(weekday)
    elif kind == "once":
        run_at = _parse_once_datetime(str(args.get("date") or ""), hour, minute)
        if run_at is None:
            return {"success": False, "error": "once 任务需要 date（YYYY-MM-DD 或 今天/明天/后天）"}

    now = datetime.now()
    next_run_at = compute_next_run(kind, hour, minute, weekday, run_at, now)
    if next_run_at is None:
        return {"success": False, "error": "指定时刻已过，请换一个将来的时间"}

    task = ScheduledTask(
        user_id=user.id,
        title=title,
        instruction=instruction,
        kind=kind,
        hour=hour,
        minute=minute,
        weekday=weekday,
        run_at=run_at,
        enabled=1,
        next_run_at=next_run_at,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {
        "success": True,
        "id": task.id,
        "title": title,
        "kind": kind,
        "next_run_at": next_run_at.strftime("%Y-%m-%d %H:%M"),
    }


@tool(
    name="list_scheduled_tasks",
    description="列出用户当前启用中的定时任务（到点自动执行并播报的任务）",
    parameters={"type": "object", "properties": {}},
)
def list_scheduled_tasks(args, user, db):
    from ..models import ScheduledTask

    rows = (
        db.query(ScheduledTask)
        .filter(ScheduledTask.user_id == user.id, ScheduledTask.enabled == 1)
        .order_by(ScheduledTask.next_run_at.asc())
        .all()
    )
    return {
        "success": True,
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "instruction": t.instruction,
                "kind": t.kind,
                "next_run_at": t.next_run_at.strftime("%Y-%m-%d %H:%M") if t.next_run_at else None,
            }
            for t in rows
        ],
    }


@tool(
    name="cancel_scheduled_task",
    description="取消（停用）一个定时任务；先用 list_scheduled_tasks 查到任务 id",
    parameters={
        "type": "object",
        "properties": {"task_id": {"type": "integer", "description": "要取消的任务 id"}},
        "required": ["task_id"],
    },
)
def cancel_scheduled_task(args, user, db):
    from ..models import ScheduledTask

    task_id = args.get("task_id")
    task = (
        db.query(ScheduledTask)
        .filter(ScheduledTask.id == task_id, ScheduledTask.user_id == user.id)
        .first()
    )
    if task is None:
        return {"success": False, "error": f"找不到任务 {task_id}（或不属于当前用户）"}
    task.enabled = 0
    db.commit()
    return {"success": True, "cancelled": task.title}
