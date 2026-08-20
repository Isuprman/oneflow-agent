# schedule_event / list_schedule — 日程，真实 SQLite 持久化
from datetime import datetime, timedelta

from ..models import Schedule
from .registry import tool


def _parse_dt(value):
    if value is None or not str(value).strip():
        return None
    try:
        # 兼容 "YYYY-MM-DD HH:MM" 与 ISO 格式
        return datetime.fromisoformat(str(value).replace(" ", "T"))
    except ValueError:
        return None


@tool(
    name="schedule_event",
    description="添加一条日程",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "日程标题"},
            "start_at": {"type": "string", "description": "YYYY-MM-DD HH:MM 或 ISO 格式"},
            "end_at": {"type": "string", "description": "YYYY-MM-DD HH:MM 或 ISO 格式，可选"},
        },
        "required": ["title", "start_at"],
    },
)
def schedule_event(args, user, db):
    title = args.get("title")
    start = _parse_dt(args.get("start_at"))
    if not title:
        return {"success": False, "error": "缺少标题"}
    if start is None:
        return {"success": False, "error": "时间格式错误"}
    end = _parse_dt(args.get("end_at"))

    sched = Schedule(user_id=user.id, title=title, start_at=start, end_at=end)
    db.add(sched)
    db.commit()
    db.refresh(sched)
    return {
        "success": True,
        "id": sched.id,
        "title": sched.title,
        "start_at": sched.start_at.isoformat(),
        "end_at": sched.end_at.isoformat() if sched.end_at else None,
    }


@tool(
    name="list_schedule",
    description="查询当前用户的日程（可按日期过滤；不传则返回未来日程）",
    parameters={
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "YYYY-MM-DD，可选，过滤当天"},
        },
    },
)
def list_schedule(args, user, db):
    date = args.get("date")
    q = db.query(Schedule).filter(Schedule.user_id == user.id)
    if date:
        try:
            day = datetime.fromisoformat(date)
        except ValueError:
            return {"success": False, "error": "日期格式错误"}
        q = q.filter(Schedule.start_at >= day, Schedule.start_at < day + timedelta(days=1))
    else:
        q = q.filter(Schedule.start_at >= datetime.now())
    items = q.order_by(Schedule.start_at.asc()).all()

    return {
        "success": True,
        "items": [
            {
                "id": s.id,
                "title": s.title,
                "start_at": s.start_at.isoformat(),
                "end_at": s.end_at.isoformat() if s.end_at else None,
            }
            for s in items
        ],
    }
