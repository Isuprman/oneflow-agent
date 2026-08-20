# 定时任务工具测试 — 直接打 DB，无 LLM 依赖
from datetime import datetime, timedelta

from app.models import ScheduledTask, User
from app.tools.registry import execute


def _new_user(db, username):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_create_daily_task(db_session):
    db = db_session()
    user = _new_user(db, "sched_daily")
    result = execute(
        "create_scheduled_task",
        {"title": "早间播报", "instruction": "查询上海天气并播报", "kind": "daily", "hour": 8, "minute": 0},
        user,
        db,
    )
    assert result["success"] is True
    assert result["kind"] == "daily"
    task = db.query(ScheduledTask).filter(ScheduledTask.id == result["id"]).first()
    assert task.enabled == 1
    # 下次执行必然是未来的 08:00
    assert task.next_run_at > datetime.now()
    assert task.next_run_at.hour == 8 and task.next_run_at.minute == 0
    db.close()


def test_create_weekly_requires_weekday(db_session):
    db = db_session()
    user = _new_user(db, "sched_weekly")
    result = execute(
        "create_scheduled_task",
        {"title": "周报提醒", "instruction": "提醒我交周报", "kind": "weekly", "hour": 17},
        user,
        db,
    )
    assert result["success"] is False
    assert "weekday" in result["error"]

    ok = execute(
        "create_scheduled_task",
        {"title": "周报提醒", "instruction": "提醒我交周报", "kind": "weekly", "hour": 17, "weekday": 5},
        user,
        db,
    )
    assert ok["success"] is True
    db.close()


def test_create_once_past_time_rejected(db_session):
    db = db_session()
    user = _new_user(db, "sched_once")
    past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    result = execute(
        "create_scheduled_task",
        {"title": "过期任务", "instruction": "x", "kind": "once", "hour": 9, "date": past},
        user,
        db,
    )
    assert result["success"] is False
    assert "已过" in result["error"]

    tomorrow = execute(
        "create_scheduled_task",
        {"title": "开会提醒", "instruction": "提醒我开会", "kind": "once", "hour": 15, "date": "明天"},
        user,
        db,
    )
    assert tomorrow["success"] is True
    db.close()


def test_list_and_cancel_task(db_session):
    db = db_session()
    user = _new_user(db, "sched_list")
    created = execute(
        "create_scheduled_task",
        {"title": "待取消", "instruction": "x", "kind": "daily", "hour": 10},
        user,
        db,
    )
    listed = execute("list_scheduled_tasks", {}, user, db)
    assert listed["success"] is True
    assert any(t["id"] == created["id"] for t in listed["tasks"])

    cancelled = execute("cancel_scheduled_task", {"task_id": created["id"]}, user, db)
    assert cancelled["success"] is True
    listed_after = execute("list_scheduled_tasks", {}, user, db)
    assert all(t["id"] != created["id"] for t in listed_after["tasks"])

    # 别人的任务不能取消
    other = _new_user(db, "sched_other")
    foreign = execute("cancel_scheduled_task", {"task_id": created["id"]}, other, db)
    assert foreign["success"] is False
    db.close()
