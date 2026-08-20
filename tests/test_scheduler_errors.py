# 调度失败自报测试 — LLM 错误人话化 + system_error 分类 + 每日防刷屏
import asyncio
from datetime import datetime, timedelta

from app.models import Notification, ScheduledTask, User
from app.scheduler import _execute_task, _friendly_llm_error, notify_system_error


def _setup(db, username):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _due_task(db, user, title="早间播报"):
    task = ScheduledTask(
        user_id=user.id,
        title=title,
        instruction="x",
        kind="daily",
        hour=8,
        minute=0,
        enabled=1,
        next_run_at=datetime.now() - timedelta(seconds=1),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def test_friendly_llm_error_classification():
    assert _friendly_llm_error("LLM 调用出错: litellm.RateLimitError...") is not None
    assert _friendly_llm_error("LLM 未配置：请先在设置页填写密钥") is not None
    # 普通回复与工具错误不算 LLM 错误
    assert _friendly_llm_error("早安！今天晴") is None
    assert _friendly_llm_error("定时任务执行失败: boom") is None


def test_task_llm_failure_notifies_system_error(db_session, monkeypatch):
    db = db_session()
    user = _setup(db, "sched_err")
    task = _due_task(db, user)

    async def err_agent(db_, user_, conv_id, msg, **kwargs):
        return "LLM 调用出错: boom", 1, []

    monkeypatch.setattr("app.agent.engine.run_agent", err_agent)
    asyncio.run(_execute_task(db, task))

    db.expire_all()
    notes = db.query(Notification).filter(Notification.user_id == user.id).all()
    assert len(notes) == 1
    assert notes[0].kind == "system_error"
    # 人话化：不含原始报错，含可操作建议
    assert "LLM 调用出错" not in notes[0].content
    assert "检查" in notes[0].content
    db.close()


def test_task_exception_notifies_normally(db_session, monkeypatch):
    db = db_session()
    user = _setup(db, "sched_exc")
    task = _due_task(db, user)

    async def boom(db_, user_, conv_id, msg, **kwargs):
        raise RuntimeError("炸了")

    monkeypatch.setattr("app.agent.engine.run_agent", boom)
    asyncio.run(_execute_task(db, task))

    db.expire_all()
    notes = db.query(Notification).filter(Notification.user_id == user.id).all()
    assert len(notes) == 1
    assert notes[0].kind == "task"  # 非 LLM 错误照常播报
    db.close()


def test_notify_system_error_once_per_day(db_session):
    db = db_session()
    _setup(db, "syserr_user")

    notify_system_error(db, "第一次异常")
    notify_system_error(db, "第二次异常")  # 同日应被拦截

    db.expire_all()
    notes = db.query(Notification).filter(Notification.kind == "system_error").all()
    assert len(notes) == 1
    assert "第一次异常" in notes[0].content
    db.close()
