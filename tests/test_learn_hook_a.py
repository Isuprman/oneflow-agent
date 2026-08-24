# TaskA — 确认式学习流 + 听写纠错 钩子单测（构建与 LLM 全部桩替，不依赖真实外网）
import asyncio
import time
from types import SimpleNamespace

import pytest

from app.learn import hook
from app.learn.hook import is_learn_message, pending_intents, try_handle

RAW = "你要是能查快递就好了"

FAKE_PROPOSAL = SimpleNamespace(
    id=7, slug="demo_express", title="查快递", status="pending",
    required_keys="{}", test_output="",
)


@pytest.fixture(autouse=True)
def _clean_pending():
    pending_intents.clear()
    yield
    pending_intents.clear()


@pytest.fixture()
def session(db_session):
    s = db_session()
    yield s
    s.close()


@pytest.fixture()
def user(session):
    from app.models import Conversation, User

    u = User(username="hooka", password_hash="x")
    session.add(u)
    session.commit()
    session.add(Conversation(user_id=u.id, title="t"))
    session.commit()
    return u


@pytest.fixture()
def conv_id(user, session):
    from app.models import Conversation

    return session.query(Conversation).filter_by(user_id=user.id).first().id


@pytest.fixture(autouse=True)
def build_calls(monkeypatch):
    """桩掉构建：记录入参，返回假提案。"""
    calls: list[str] = []

    def fake_build(db, u, request_text, cfg):
        calls.append(request_text)
        return FAKE_PROPOSAL

    monkeypatch.setattr(hook.service, "build_proposal", fake_build)
    return calls


@pytest.fixture()
def passthrough_asr(monkeypatch):
    async def fake_correct(text, cfg):
        return text

    monkeypatch.setattr(hook, "correct_asr_text", fake_correct)


def _handle(session, user, conv_id, msg, **kwargs):
    return asyncio.run(try_handle(session, user, conv_id, msg, **kwargs))


# ─── 两段式确认流 ──────────────────────────────────────────────────

def test_first_hit_only_confirms_without_build(session, user, conv_id, build_calls, passthrough_asr):
    reply = _handle(session, user, conv_id, RAW)
    assert "确认一下" in reply and RAW in reply
    assert "取消" in reply
    assert build_calls == []
    assert pending_intents[user.id]["raw"] == RAW


def test_confirm_builds_once_with_stored_raw(session, user, conv_id, build_calls, passthrough_asr):
    pending_intents[user.id] = {"raw": RAW, "ts": time.time()}
    reply = _handle(session, user, conv_id, "确认")
    assert build_calls == [RAW]
    assert "提案编号 #7" in reply
    assert user.id not in pending_intents


def test_correction_updates_raw_and_reawaits(session, user, conv_id, build_calls, passthrough_asr):
    pending_intents[user.id] = {"raw": "你要是能学会计就好了", "ts": time.time()}
    reply = _handle(session, user, conv_id, "不对我要的是查快递")
    assert build_calls == []
    assert "确认一下" in reply and "不对我要的是查快递" in reply
    assert pending_intents[user.id]["raw"] == "不对我要的是查快递"


def test_cancel_clears_pending(session, user, conv_id, build_calls, passthrough_asr):
    pending_intents[user.id] = {"raw": RAW, "ts": time.time()}
    reply = _handle(session, user, conv_id, "取消")
    assert reply == "好的，已取消。"
    assert user.id not in pending_intents
    assert build_calls == []


def test_approval_commands_bypass_confirm_flow(session, user, conv_id, build_calls, passthrough_asr):
    from app.models import SkillProposal

    proposal = SkillProposal(
        user_id=user.id, slug="demo_echo", title="回显", description="",
        status="pending", tool_code="", test_code="", test_output="",
        required_keys="{}", branch="",
    )
    session.add(proposal)
    session.commit()

    pending_intents[user.id] = {"raw": RAW, "ts": time.time()}
    reply = _handle(session, user, conv_id, f"拒绝 {proposal.id}")
    assert "放弃" in reply
    session.refresh(proposal)
    assert proposal.status == "rejected"
    assert pending_intents[user.id]["raw"] == RAW  # 待确认意图不受影响
    assert build_calls == []


# ─── 听写纠错 ──────────────────────────────────────────────────────

def test_correct_asr_degrades_on_llm_failure(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr("app.agent.llm.chat", boom)
    out = asyncio.run(hook.correct_asr_text(RAW, {"api_key": "k"}))
    assert out == RAW


def test_first_hit_uses_corrected_text_in_prompt(session, user, conv_id, build_calls, monkeypatch):
    async def fake_correct(text, cfg):
        return "你要是能查快递就好了"

    monkeypatch.setattr(hook, "correct_asr_text", fake_correct)
    reply = _handle(session, user, conv_id, "你要是能学会计就好了")
    assert "【你要是能查快递就好了】" in reply
    assert pending_intents[user.id]["raw"] == "你要是能查快递就好了"


# ─── 构建进度直播 ─────────────────────────────────────────────────

def test_on_progress_stages_emitted(session, user, conv_id, build_calls, passthrough_asr):
    pending_intents[user.id] = {"raw": RAW, "ts": time.time()}
    stages: list[str] = []
    _handle(session, user, conv_id, "确认", on_progress=stages.append)
    assert stages[:3] == ["正在理解需求…", "正在设计工具与测试…", "沙箱验证中…"]
    assert stages[-1] == "候选已提交，等待确认上线"


def test_no_progress_callback_is_fine(session, user, conv_id, build_calls, passthrough_asr):
    pending_intents[user.id] = {"raw": RAW, "ts": time.time()}
    reply = _handle(session, user, conv_id, "确认")
    assert "提案编号 #7" in reply


# ─── 接口不变量 ───────────────────────────────────────────────────

def test_non_learn_message_returns_none(session, user, conv_id, build_calls, passthrough_asr):
    assert _handle(session, user, conv_id, "今天天气怎么样") is None
    assert build_calls == []
    assert user.id not in pending_intents


def test_is_learn_message_unchanged():
    assert is_learn_message(RAW)
    assert is_learn_message("批准 12")
    assert not is_learn_message("嗯")
