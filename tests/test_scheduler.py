# 调度引擎测试 — compute_next_run 纯函数 + tick 到期执行（mock agent 执行，仅测试允许）
import asyncio
from datetime import datetime, timedelta

import app.scheduler as scheduler_mod
from app.models import Notification, Schedule, ScheduledTask, User
from app.scheduler import compute_next_run, tick


# ---------- compute_next_run ----------

def test_once_future_and_past():
    now = datetime(2026, 8, 21, 10, 0)
    future = datetime(2026, 8, 22, 15, 30)
    assert compute_next_run("once", 15, 30, None, future, now) == future
    past = datetime(2026, 8, 20, 9, 0)
    assert compute_next_run("once", 9, 0, None, past, now) is None


def test_daily_today_or_tomorrow():
    now = datetime(2026, 8, 21, 7, 0)  # 早于 8 点：取今天
    assert compute_next_run("daily", 8, 0, None, None, now) == datetime(2026, 8, 21, 8, 0)
    now2 = datetime(2026, 8, 21, 9, 0)  # 晚于 8 点：取明天
    assert compute_next_run("daily", 8, 0, None, None, now2) == datetime(2026, 8, 22, 8, 0)


def test_weekly_nearest_weekday():
    # 2026-08-21 是周五（weekday=4）
    now = datetime(2026, 8, 21, 10, 0)
    # 目标周一（weekday=1）：下周一 8/24
    assert compute_next_run("weekly", 9, 0, 1, None, now) == datetime(2026, 8, 24, 9, 0)
    # 目标周五且时刻已过：下周五 8/28
    assert compute_next_run("weekly", 9, 0, 5, None, now) == datetime(2026, 8, 28, 9, 0)
    # 目标周日（weekday=7）：本周日 8/23
    assert compute_next_run("weekly", 9, 0, 7, None, now) == datetime(2026, 8, 23, 9, 0)


# ---------- tick ----------

def _setup(db, username):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_tick_executes_due_task_and_creates_notification(db_session, monkeypatch):
    db = db_session()
    user = _setup(db, "tick_user")
    task = ScheduledTask(
        user_id=user.id,
        title="早间播报",
        instruction="查询天气并播报",
        kind="daily",
        hour=8,
        minute=0,
        enabled=1,
        next_run_at=datetime.now() - timedelta(seconds=1),  # 已到期
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    async def fake_run_agent(db_, user_, conv_id, msg, **kwargs):
        return "早安！今天晴，25 度。", 1, []

    monkeypatch.setattr("app.agent.engine.run_agent", fake_run_agent)
    monkeypatch.setattr(scheduler_mod, "SessionLocal", db_session)

    asyncio.run(tick())

    db.expire_all()
    notes = db.query(Notification).filter(Notification.user_id == user.id).all()
    assert len(notes) == 1
    assert notes[0].kind == "task"
    assert "早安" in notes[0].content

    # daily 任务已推进到下一次（未来），仍启用
    refreshed = db.query(ScheduledTask).filter(ScheduledTask.id == task.id).first()
    assert refreshed.enabled == 1
    assert refreshed.next_run_at > datetime.now()

    # 再跑一次 tick：未到期的任务不应重复执行
    asyncio.run(tick())
    db.expire_all()
    assert db.query(Notification).filter(Notification.user_id == user.id).count() == 1
    db.close()


def test_tick_once_task_disabled_after_run(db_session, monkeypatch):
    db = db_session()
    user = _setup(db, "tick_once")
    task = ScheduledTask(
        user_id=user.id,
        title="开会提醒",
        instruction="提醒我开会",
        kind="once",
        hour=15,
        minute=0,
        enabled=1,
        next_run_at=datetime.now() - timedelta(seconds=1),
    )
    db.add(task)
    db.commit()

    async def fake_run_agent(db_, user_, conv_id, msg, **kwargs):
        return "该开会了", 1, []

    monkeypatch.setattr("app.agent.engine.run_agent", fake_run_agent)
    monkeypatch.setattr(scheduler_mod, "SessionLocal", db_session)

    asyncio.run(tick())

    db.expire_all()
    refreshed = db.query(ScheduledTask).filter(ScheduledTask.user_id == user.id).first()
    assert refreshed.enabled == 0
    assert refreshed.next_run_at is None
    assert db.query(Notification).filter(Notification.user_id == user.id).count() == 1
    db.close()


def test_tick_reminds_due_schedule_event(db_session, monkeypatch):
    db = db_session()
    user = _setup(db, "tick_remind")
    event = Schedule(
        user_id=user.id,
        title="产品评审",
        start_at=datetime.now() + timedelta(minutes=2),  # 落在提醒窗口内
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    monkeypatch.setattr(scheduler_mod, "SessionLocal", db_session)
    asyncio.run(tick())

    db.expire_all()
    notes = db.query(Notification).filter(Notification.user_id == user.id).all()
    assert len(notes) == 1
    assert notes[0].kind == "reminder"
    assert "产品评审" in notes[0].content

    # 已标记 notified，再次 tick 不重复提醒
    asyncio.run(tick())
    db.expire_all()
    assert db.query(Notification).filter(Notification.user_id == user.id).count() == 1
    db.close()
