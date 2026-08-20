# delegate 委派集成测试 — 总控 -> 子智能体 -> 总控收尾
import asyncio

from app.agent.engine import run_agent
from app.agent.llm import LLMResult, ToolCall
from app.models import Conversation, Expense, User


def _new_conv(db, username):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    conv = Conversation(user_id=user.id, title="t")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return user, conv


def test_delegate_delegates_to_subagent(db_session, monkeypatch):
    db = db_session()
    user, conv = _new_conv(db, "del_finance")

    counter = {"n": 0}

    async def fake_chat(messages, tools, cfg=None, on_delta=None):
        counter["n"] += 1
        if counter["n"] == 1:  # 总控：委派 finance
            return LLMResult(
                tool_call=ToolCall("delegate", {"agent_name": "finance", "instruction": "记一笔50元午饭"})
            )
        if counter["n"] == 2:  # 子智能体 finance：执行记账
            return LLMResult(
                tool_call=ToolCall("add_expense", {"amount": 50, "category": "餐饮", "note": "午饭"})
            )
        if counter["n"] == 3:  # 子智能体 finance：给结论
            return LLMResult(text="已记 50 元")
        return LLMResult(text="好，已帮你记好")  # 总控收尾

    monkeypatch.setattr("app.agent.llm.chat", fake_chat)

    reply, steps, trace = asyncio.run(run_agent(db, user, conv.id, "记一笔50元午饭"))

    assert "好" in reply
    assert len(trace) >= 1
    assert trace[0]["tool"] == "delegate"
    assert trace[0]["result"]["success"] is True

    db.expire_all()
    exps = db.query(Expense).filter(Expense.user_id == user.id).all()
    assert len(exps) == 1
    db.close()
