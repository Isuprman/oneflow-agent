# TaskT — 信任旋钮：三档自治等级下的工具确认行为（LLM 与执行路径全部桩替，不依赖真实外网）
#
# ask_all ：每个工具调用前都走既有 pending 确认流（含只读工具）
# standard：现状——仅高危写操作确认，只读工具直接执行（默认档）
# auto    ：普通写操作跳过确认直接执行；删除类高危仍强制确认；学习提案审批永不跳过
import asyncio

import pytest

from app.agent.engine import run_agent
from app.agent.llm import LLMResult, ToolCall
from app.learn.hook import (
    TRUST_DEFAULT,
    TRUST_KEY,
    get_trust_level,
    pending_intents,
    try_handle,
)
from app.models import Conversation, CustomAgent, Expense, PendingAction, User, UserSetting


@pytest.fixture(autouse=True)
def _clean_pending():
    """try_handle 的 pending_intents 是进程内全局态，测试前后清空防串扰。"""
    pending_intents.clear()
    yield
    pending_intents.clear()


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


def _set_trust(db, user_id: int, level: str) -> None:
    row = db.query(UserSetting).filter_by(user_id=user_id, key=TRUST_KEY).first()
    if row is None:
        db.add(UserSetting(user_id=user_id, key=TRUST_KEY, value=level))
    else:
        row.value = level
    db.commit()


# ─── 读取封装 ──────────────────────────────────────────────────────

def test_get_trust_level_defaults(db_session):
    db = db_session()
    user, _conv = _setup(db, "trust_default")

    assert get_trust_level(db, user.id) == "standard"  # 未设置回退默认档

    _set_trust(db, user.id, "auto")
    assert get_trust_level(db, user.id) == "auto"

    _set_trust(db, user.id, "yolo")
    assert get_trust_level(db, user.id) == TRUST_DEFAULT  # 非法值一律回退
    db.close()


# ─── ask_all 档 ────────────────────────────────────────────────────

def test_ask_all_confirms_even_readonly_tools(db_session, monkeypatch):
    db = db_session()
    user, conv = _setup(db, "trust_ask_all")
    _set_trust(db, user.id, "ask_all")

    async def fake_chat(messages, tools, cfg=None, on_delta=None):
        return LLMResult(tool_call=ToolCall("calculate", {"expression": "1+1"}))

    def boom(name, args, user_, db_, cfg=None):
        raise AssertionError("ask_all 档只读工具也应先进确认分支，不应直接执行")

    monkeypatch.setattr("app.agent.llm.chat", fake_chat)
    monkeypatch.setattr("app.agent.engine.execute", boom)

    events = []
    reply, steps, trace = asyncio.run(
        run_agent(db, user, conv.id, "帮我算下 1+1", on_event=events.append)
    )

    assert "确认" in reply
    assert trace == []  # 未执行
    pending = db.query(PendingAction).filter_by(user_id=user.id).first()
    assert pending is not None and pending.tool_name == "calculate"
    assert any(e.get("type") == "confirm" for e in events)
    db.close()


# ─── standard 档（现状基线）─────────────────────────────────────────

def test_standard_runs_readonly_tool_directly(db_session, monkeypatch):
    db = db_session()
    user, conv = _setup(db, "trust_standard")
    # 故意不写 trust.level —— 默认即 standard

    seq = {"n": 0}

    async def fake_chat(messages, tools, cfg=None, on_delta=None):
        seq["n"] += 1
        if seq["n"] == 1:
            return LLMResult(tool_call=ToolCall("calculate", {"expression": "2*3"}))
        return LLMResult(text="等于 6")

    monkeypatch.setattr("app.agent.llm.chat", fake_chat)

    reply, steps, trace = asyncio.run(run_agent(db, user, conv.id, "算 2*3"))

    assert reply == "等于 6"
    assert [t["tool"] for t in trace] == ["calculate"]
    assert db.query(PendingAction).filter_by(user_id=user.id).count() == 0
    db.close()


def test_standard_write_still_asks_confirmation(db_session, monkeypatch):
    db = db_session()
    user, conv = _setup(db, "trust_std_write")

    async def fake_chat(messages, tools, cfg=None, on_delta=None):
        return LLMResult(tool_call=ToolCall("add_expense", {"amount": 50, "category": "餐饮"}))

    monkeypatch.setattr("app.agent.llm.chat", fake_chat)

    events = []
    reply, steps, trace = asyncio.run(
        run_agent(db, user, conv.id, "记一笔50元午饭", on_event=events.append)
    )

    assert "确认" in reply and trace == []
    assert db.query(Expense).filter_by(user_id=user.id).count() == 0
    assert any(e.get("type") == "confirm" for e in events)
    db.close()


# ─── auto 档 ───────────────────────────────────────────────────────

def test_auto_executes_plain_write_without_confirm(db_session, monkeypatch):
    db = db_session()
    user, conv = _setup(db, "trust_auto_write")
    _set_trust(db, user.id, "auto")

    seq = {"n": 0}

    async def fake_chat(messages, tools, cfg=None, on_delta=None):
        seq["n"] += 1
        if seq["n"] == 1:
            return LLMResult(tool_call=ToolCall("add_expense", {"amount": 66, "category": "交通"}))
        return LLMResult(text="已记好 66 元交通支出")

    monkeypatch.setattr("app.agent.llm.chat", fake_chat)

    events = []
    reply, steps, trace = asyncio.run(
        run_agent(db, user, conv.id, "打车花了66块记一下", on_event=events.append)
    )

    assert reply == "已记好 66 元交通支出"
    assert [t["tool"] for t in trace] == ["add_expense"] and trace[0]["success"] is True
    assert not any(e.get("type") == "confirm" for e in events)  # 普通写操作跳过确认
    db.expire_all()
    assert db.query(Expense).filter_by(user_id=user.id).count() == 1
    assert db.query(PendingAction).filter_by(user_id=user.id).count() == 0
    db.close()


def test_auto_still_confirms_destructive_high_risk(db_session, monkeypatch):
    db = db_session()
    user, conv = _setup(db, "trust_auto_highrisk")
    db.add(CustomAgent(user_id=user.id, name="researcher", persona="p", tools="[]"))
    db.commit()
    _set_trust(db, user.id, "auto")

    async def fake_chat(messages, tools, cfg=None, on_delta=None):
        return LLMResult(tool_call=ToolCall("delete_custom_agent", {"name": "researcher"}))

    monkeypatch.setattr("app.agent.llm.chat", fake_chat)

    events = []
    reply, steps, trace = asyncio.run(
        run_agent(db, user, conv.id, "删掉 researcher", on_event=events.append)
    )

    assert "确认" in reply and trace == []  # 删除类高危仍强制确认
    pending = db.query(PendingAction).filter_by(user_id=user.id).first()
    assert pending is not None and pending.tool_name == "delete_custom_agent"
    assert db.query(CustomAgent).filter_by(user_id=user.id, name="researcher").count() == 1
    assert any(e.get("type") == "confirm" for e in events)
    db.close()


# ─── 安全底线：学习提案审批不受信任等级影响 ─────────────────────────

def test_auto_keeps_learn_proposal_confirmation(db_session, monkeypatch):
    db = db_session()
    user, conv = _setup(db, "trust_auto_learn")
    _set_trust(db, user.id, "auto")

    from app.learn import hook

    async def passthrough_asr(text, cfg):
        return text

    async def no_similar(db_, uid, q, cfg_, top_k=3):
        return []

    monkeypatch.setattr(hook, "correct_asr_text", passthrough_asr)
    monkeypatch.setattr("app.learn.retrieval.search_similar", no_similar)

    reply = asyncio.run(try_handle(db, user, conv.id, "教你会翻译古文"))

    assert "确认一下" in reply  # auto 档仍先复述等确认，不直接构建
    assert pending_intents[user.id]["kind"] == "confirm"
