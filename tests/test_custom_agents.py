# 自定义子智能体测试 — 工具 CRUD + 解析合并 + delegate 动态路由
import asyncio
import json

from app.agent.engine import run_agent
from app.agent.llm import LLMResult, ToolCall
from app.agent.subagent import resolve_agent
from app.models import Conversation, CustomAgent, User
from app.tools.registry import execute


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


def test_create_and_list_custom_agent(db_session):
    db = db_session()
    user, _ = _setup(db, "ca_create")
    created = execute(
        "create_custom_agent",
        {"name": "fitness", "persona": "你是专业健身教练", "tools": ["schedule_event", "calculate"]},
        user,
        db,
    )
    assert created["success"] is True

    listed = execute("list_custom_agents", {}, user, db)
    assert listed["success"] is True
    assert listed["agents"][0]["name"] == "fitness"
    db.close()


def test_create_rejects_reserved_name_and_bad_tools(db_session):
    db = db_session()
    user, _ = _setup(db, "ca_reject")
    reserved = execute(
        "create_custom_agent",
        {"name": "life", "persona": "x", "tools": ["calculate"]},
        user,
        db,
    )
    assert reserved["success"] is False

    bad_tool = execute(
        "create_custom_agent",
        {"name": "x", "persona": "x", "tools": ["no_such_tool"]},
        user,
        db,
    )
    assert bad_tool["success"] is False
    db.close()


def test_resolve_agent_merges_builtin_and_custom(db_session):
    db = db_session()
    user, _ = _setup(db, "ca_resolve")
    assert resolve_agent(db, user.id, "life") is not None  # 内置
    assert resolve_agent(db, user.id, "ghost") is None

    db.add(
        CustomAgent(
            user_id=user.id,
            name="coach",
            persona="你是教练",
            tools=json.dumps(["calculate"]),
        )
    )
    db.commit()
    custom = resolve_agent(db, user.id, "coach")
    assert custom is not None
    assert custom["system"] == "你是教练"
    assert custom["tools"] == ["calculate"]

    # 别的用户看不到
    other, _ = _setup(db, "ca_other")
    assert resolve_agent(db, other.id, "coach") is None
    db.close()


def test_delegate_to_custom_agent(db_session, monkeypatch):
    db = db_session()
    user, conv = _setup(db, "ca_delegate")
    db.add(
        CustomAgent(
            user_id=user.id,
            name="coach",
            persona="你是教练，用简洁中文给结论",
            tools=json.dumps(["calculate"]),
        )
    )
    db.commit()

    counter = {"n": 0}

    async def fake_chat(messages, tools, cfg=None, on_delta=None, **kwargs):
        counter["n"] += 1
        if counter["n"] == 1:  # 总控：委派自定义 agent
            return LLMResult(tool_call=ToolCall("delegate", {"agent_name": "coach", "instruction": "算 2+2"}))
        if counter["n"] == 2:  # 子智能体：调工具
            return LLMResult(tool_call=ToolCall("calculate", {"expression": "2+2"}))
        if counter["n"] == 3:  # 子智能体：给结论
            return LLMResult(text="结果是 4")
        return LLMResult(text="教练算好了")  # 总控收尾

    monkeypatch.setattr("app.agent.llm.chat", fake_chat)

    reply, steps, trace = asyncio.run(run_agent(db, user, conv.id, "让教练算个数"))
    assert reply == "教练算好了"
    assert trace[0]["tool"] == "delegate"
    assert trace[0]["result"]["agent"] == "coach"
    db.close()
