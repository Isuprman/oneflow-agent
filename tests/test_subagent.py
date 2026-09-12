# 子智能体测试 — mock app.agent.llm.chat
import asyncio

import pytest

from app.agent.llm import LLMResult, ToolCall
from app.agent.subagent import run_subagent
from app.config import settings
from app.models import Expense, User


def _new_user(db, username):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_subagent_executes_tool_and_returns_text(db_session, monkeypatch):
    db = db_session()
    user = _new_user(db, "sub_finance")

    replies = [
        LLMResult(tool_call=ToolCall("add_expense", {"amount": 50, "category": "餐饮", "note": "午饭"})),
        LLMResult(text="已记 50 元餐饮"),
    ]

    async def fake_chat(messages, tools, cfg=None, on_delta=None, **kwargs):
        return replies.pop(0)

    monkeypatch.setattr("app.agent.llm.chat", fake_chat)

    text, steps = asyncio.run(run_subagent(db, user, "finance", "帮我记一笔午饭50", "无"))

    assert "50" in text
    assert steps >= 2

    db.expire_all()
    exps = db.query(Expense).filter(Expense.user_id == user.id).all()
    assert len(exps) == 1
    assert exps[0].amount == 50
    db.close()


def test_subagent_unknown_name_raises(db_session):
    db = db_session()
    user = _new_user(db, "sub_unknown")

    with pytest.raises(ValueError):
        asyncio.run(run_subagent(db, user, "xxx", "hi", "无"))
    db.close()


def test_subagent_step_breaker(db_session, monkeypatch):
    db = db_session()
    user = _new_user(db, "sub_breaker")
    monkeypatch.setattr(settings, "max_steps", 3)

    async def always_tool(messages, tools, cfg=None, on_delta=None, **kwargs):
        return LLMResult(tool_call=ToolCall("add_expense", {"amount": 1, "category": "餐饮"}))

    monkeypatch.setattr("app.agent.llm.chat", always_tool)

    text, steps = asyncio.run(run_subagent(db, user, "finance", "记账", "无"))

    assert "未能在限定步数内完成" in text
    assert steps > 1
    db.close()
