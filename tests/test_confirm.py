# 高危操作确认流程测试 — engine 拦截写操作 → 用户确认/取消
import asyncio
import json

from app.agent.engine import run_agent
from app.agent.llm import LLMResult, ToolCall
from app.models import Conversation, Expense, PendingAction, User


def _setup(db, username):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    conv = Conversation(user_id=user.id, title="t")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return user, conv


def test_high_risk_tool_asks_confirmation(db_session, monkeypatch):
    db = db_session()
    user, conv = _setup(db, "confirm_ask")

    async def fake_chat(messages, tools, cfg=None, on_delta=None):
        return LLMResult(tool_call=ToolCall("add_expense", {"amount": 50, "category": "餐饮"}))

    monkeypatch.setattr("app.agent.llm.chat", fake_chat)

    events = []
    reply, steps, trace = asyncio.run(
        run_agent(db, user, conv.id, "记一笔50元午饭", on_event=events.append)
    )

    # 拦截：未执行、回复请求确认、pending 已落库、confirm 事件已推
    assert db.query(Expense).filter(Expense.user_id == user.id).count() == 0
    assert "确认" in reply
    pending = db.query(PendingAction).filter(PendingAction.user_id == user.id).first()
    assert pending is not None and pending.tool_name == "add_expense"
    assert any(e.get("type") == "confirm" for e in events)
    db.close()


def test_confirm_executes_pending(db_session, monkeypatch):
    db = db_session()
    user, conv = _setup(db, "confirm_yes")
    db.add(
        PendingAction(
            user_id=user.id,
            conversation_id=conv.id,
            tool_name="add_expense",
            arguments=json.dumps({"amount": 30, "category": "交通"}, ensure_ascii=False),
            summary="我将为您记一笔支出：30 元（交通）",
        )
    )
    db.commit()

    async def fake_chat(messages, tools, cfg=None, on_delta=None):
        return LLMResult(text="已为您记好")

    monkeypatch.setattr("app.agent.llm.chat", fake_chat)

    reply, steps, trace = asyncio.run(run_agent(db, user, conv.id, "确认"))

    assert reply == "已为您记好"
    assert len(trace) == 1 and trace[0]["tool"] == "add_expense"
    db.expire_all()
    assert db.query(Expense).filter(Expense.user_id == user.id).count() == 1
    assert db.query(PendingAction).filter(PendingAction.user_id == user.id).count() == 0
    db.close()


def test_cancel_discards_pending_without_llm(db_session, monkeypatch):
    db = db_session()
    user, conv = _setup(db, "confirm_no")
    db.add(
        PendingAction(
            user_id=user.id,
            conversation_id=conv.id,
            tool_name="add_expense",
            arguments=json.dumps({"amount": 30}),
            summary="x",
        )
    )
    db.commit()

    async def boom(messages, tools, cfg=None, on_delta=None):
        raise AssertionError("取消路径不应调用 LLM")

    monkeypatch.setattr("app.agent.llm.chat", boom)

    reply, steps, trace = asyncio.run(run_agent(db, user, conv.id, "取消"))
    assert "已取消" in reply
    db.expire_all()
    assert db.query(PendingAction).filter(PendingAction.user_id == user.id).count() == 0
    db.close()


def test_new_instruction_discards_pending(db_session, monkeypatch):
    db = db_session()
    user, conv = _setup(db, "confirm_new")
    db.add(
        PendingAction(
            user_id=user.id,
            conversation_id=conv.id,
            tool_name="add_expense",
            arguments=json.dumps({"amount": 30}),
            summary="x",
        )
    )
    db.commit()

    async def fake_chat(messages, tools, cfg=None, on_delta=None):
        return LLMResult(text="今天晴")

    monkeypatch.setattr("app.agent.llm.chat", fake_chat)

    reply, steps, trace = asyncio.run(run_agent(db, user, conv.id, "今天天气怎么样"))
    assert reply == "今天晴"
    db.expire_all()
    assert db.query(PendingAction).filter(PendingAction.user_id == user.id).count() == 0
    assert db.query(Expense).filter(Expense.user_id == user.id).count() == 0
    db.close()
