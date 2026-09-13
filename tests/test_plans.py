# 长程计划测试：工具 CRUD / 对话注入 / 每日自动推进
import asyncio

import pytest

from app.jobs import plan_advancer
from app.models import Conversation, LongTermPlan, Notification, PlanStep, User
from app.tools.registry import execute


def _make_user(db, username="plan_user"):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_plan(db, user_id, title="备考", steps=3, status="active", last_advanced_at=None):
    plan = LongTermPlan(user_id=user_id, title=title, goal="通过考试", status=status, last_advanced_at=last_advanced_at)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    for idx in range(steps):
        db.add(PlanStep(plan_id=plan.id, idx=idx, description=f"步骤{idx}"))
    db.commit()
    return plan


# ---------- 工具 ----------
def test_create_plan_creates_steps(db_session):
    db = db_session()
    user = _make_user(db)
    result = execute(
        "create_plan",
        {"title": "备考", "goal": "通过考试", "steps": ["摸底", "收集资料", "每周模拟"]},
        user,
        db,
    )
    assert result["success"] is True
    plan = db.query(LongTermPlan).filter(LongTermPlan.user_id == user.id).first()
    assert plan is not None and plan.status == "active"
    assert db.query(PlanStep).filter(PlanStep.plan_id == plan.id).count() == 3
    db.close()


def test_create_plan_caps_steps(db_session):
    db = db_session()
    user = _make_user(db)
    result = execute("create_plan", {"title": "t", "goal": "g", "steps": [f"s{i}" for i in range(30)]}, user, db)
    assert result["success"] is False
    assert "20" in result["error"]
    db.close()


def test_update_plan_step_and_status_flow(db_session):
    db = db_session()
    user = _make_user(db)
    plan = _make_plan(db, user.id)
    result = execute(
        "update_plan_step",
        {"plan_id": plan.id, "idx": 0, "status": "done", "note": "摸底完成"},
        user,
        db,
    )
    assert result["success"] is True
    step = db.query(PlanStep).filter(PlanStep.plan_id == plan.id, PlanStep.idx == 0).first()
    assert step.status == "done" and step.note == "摸底完成"

    result = execute("set_plan_status", {"plan_id": plan.id, "status": "paused"}, user, db)
    assert result["success"] is True
    db.refresh(plan)
    assert plan.status == "paused"
    db.close()


def test_plan_tools_user_isolation(db_session):
    db = db_session()
    owner = _make_user(db, "plan_owner")
    plan = _make_plan(db, owner.id)
    intruder = _make_user(db, "plan_intruder")
    result = execute("update_plan_step", {"plan_id": plan.id, "idx": 0, "status": "done"}, intruder, db)
    assert result["success"] is False
    result = execute("set_plan_status", {"plan_id": plan.id, "status": "done"}, intruder, db)
    assert result["success"] is False
    db.close()


# ---------- 对话注入 ----------
def test_active_plans_summary_injected(db_session):
    from app.tools.plans import load_active_plans_summary

    db = db_session()
    user = _make_user(db, "plan_inject")
    _make_plan(db, user.id, steps=2)
    summary = load_active_plans_summary(db, user.id)
    assert "备考" in summary and "0/2" in summary
    db.refresh(db.query(LongTermPlan).first())
    # 暂停后不再注入
    plan = db.query(LongTermPlan).first()
    plan.status = "paused"
    db.commit()
    assert load_active_plans_summary(db, user.id) == ""
    db.close()


# ---------- 每日自动推进 ----------
def test_advancer_runs_agent_and_notifies(db_session, monkeypatch):
    db = db_session()
    user = _make_user(db, "plan_adv")
    plan = _make_plan(db, user.id)
    conv = Conversation(user_id=user.id, title="计划推进")
    db.add(conv)
    db.commit()

    calls: list[str] = []

    async def fake_run_agent(db_, user_, conv_id, msg, **kw):
        calls.append(msg)
        return "先生，今天完成了第一步。", 1, []

    monkeypatch.setattr("app.agent.engine.run_agent", fake_run_agent)

    asyncio.run(plan_advancer.run(db, __import__("datetime").datetime.now()))
    assert len(calls) == 1
    assert "备考" in calls[0]
    note = db.query(Notification).filter(Notification.user_id == user.id, Notification.kind == "plan").first()
    assert note is not None and "今天完成了" in note.content
    db.refresh(plan)
    assert plan.last_advanced_at is not None
    db.close()


def test_advancer_daily_throttle(db_session, monkeypatch):
    db = db_session()
    user = _make_user(db, "plan_throttle")
    today = __import__("datetime").datetime.now()
    plan = _make_plan(db, user.id, last_advanced_at=today)
    conv = Conversation(user_id=user.id, title="计划推进")
    db.add(conv)
    db.commit()

    calls: list = []

    async def fake_run_agent(db_, user_, conv_id, msg, **kw):
        calls.append(1)
        return "推进", 1, []

    monkeypatch.setattr("app.agent.engine.run_agent", fake_run_agent)
    asyncio.run(plan_advancer.run(db, today))
    assert calls == []  # 同日已推进：跳过
    db.close()


def test_advancer_skips_paused_plans(db_session, monkeypatch):
    db = db_session()
    user = _make_user(db, "plan_paused")
    _make_plan(db, user.id, status="paused")
    conv = Conversation(user_id=user.id, title="计划推进")
    db.add(conv)
    db.commit()

    calls: list = []

    async def fake_run_agent(db_, user_, conv_id, msg, **kw):
        calls.append(1)
        return "x", 1, []

    monkeypatch.setattr("app.agent.engine.run_agent", fake_run_agent)
    asyncio.run(plan_advancer.run(db, __import__("datetime").datetime.now()))
    assert calls == []
    db.close()
