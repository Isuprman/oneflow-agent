# 情绪感知 + 数字分身测试
# 覆盖：情绪缓存与 prompt 注入 ✅ / 分身开关 ✅ / 规则触发一次不重复 ✅
import asyncio

import pytest

import app.agent.llm as llm_mod
from app.agent.llm import LLMResult
from app.learn import companion


@pytest.fixture()
def user(db_session):
    from app.models import User

    session = db_session()
    u = User(username="companion_user", password_hash="x")
    session.add(u)
    session.commit()
    session.refresh(u)
    uid = u.id
    session.close()
    return type("U", (), {"id": uid})()


@pytest.fixture(autouse=True)
def clean_mood_cache():
    """情绪缓存是模块级全局，测试间必须清空防串扰。"""
    companion._mood_cache.clear()
    yield
    companion._mood_cache.clear()


def _conversation(db_session, user_id, title="companion"):
    from app.models import Conversation

    db = db_session()
    conv = Conversation(user_id=user_id, title=title)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return db, conv


def _set_llm_key(db, user_id, key="sk-test"):
    """给用户配 LLM 密钥：情绪分类（以及 agent 主流程）前置守卫才放行。"""
    from app.models import UserSetting

    db.add(UserSetting(user_id=user_id, key="llm.api_key", value=key))
    db.commit()


# ─── 情绪感知：缓存 + prompt 注入 ──────────────────────────────────────


def test_mood_cache_and_prompt_injection(db_session, user, monkeypatch):
    """首条消息触发情绪分类并注入 prompt；10 分钟内第二条消息走缓存不再分类。"""
    from app.agent.engine import run_agent

    calls: list[list] = []

    async def fake_chat(messages, tools, cfg=None, on_delta=None, **kw):
        calls.append(messages)
        sys_text = messages[0]["content"]
        user_text = messages[-1]["content"]
        if "情绪" in sys_text:  # 情绪分类调用
            return LLMResult(text="frustrated" if "frustrated" in user_text else "calm")
        return LLMResult(text="好的")

    monkeypatch.setattr(llm_mod, "chat", fake_chat)
    db, conv = _conversation(db_session, user.id)
    _set_llm_key(db, user.id)

    asyncio.run(run_agent(db, user, conv.id, "怎么又出错了？frustrated"))
    # 首次：情绪分类 1 次 + agent 主调用 1 次
    assert len(calls) == 2
    # 分类得 frustrated → 主调用 system prompt 注入收紧指令
    assert "用户当前情绪不佳" in calls[1][0]["content"]

    asyncio.run(run_agent(db, user, conv.id, "再试一次"))
    # 第二次命中 10 分钟缓存：不再分类，只有 1 次主调用
    assert len(calls) == 3
    assert "用户当前情绪不佳" in calls[2][0]["content"]


def test_calm_no_prompt_suffix(db_session, user, monkeypatch):
    """calm 情绪不注入收紧指令。"""
    from app.agent.engine import run_agent

    calls: list[list] = []

    async def fake_chat(messages, tools, cfg=None, on_delta=None, **kw):
        calls.append(messages)
        sys_text = messages[0]["content"]
        if "情绪" in sys_text:
            return LLMResult(text="calm")
        return LLMResult(text="好的")

    monkeypatch.setattr(llm_mod, "chat", fake_chat)
    db, conv = _conversation(db_session, user.id)
    _set_llm_key(db, user.id)

    asyncio.run(run_agent(db, user, conv.id, "帮我查下天气"))
    assert len(calls) == 2
    assert "用户当前情绪不佳" not in calls[1][0]["content"]


def test_engine_intercepts_away_command(db_session, user, monkeypatch):
    """engine 层直接接管「我不在」，不触发任何 LLM 调用。"""
    from app.agent.engine import run_agent

    calls: list = []

    async def fake_chat(messages, tools, cfg=None, on_delta=None, **kw):
        calls.append(1)
        return LLMResult(text="好的")

    monkeypatch.setattr(llm_mod, "chat", fake_chat)
    db, conv = _conversation(db_session, user.id)

    reply, _steps, _trace = asyncio.run(run_agent(db, user, conv.id, "我不在"))
    assert "数字分身" in reply
    assert calls == []


def test_mood_no_key_defaults_calm(monkeypatch):
    """未配置 LLM 密钥时不发分类请求，直接按 calm 处理。"""
    calls: list = []

    async def fake_chat(messages, tools, cfg=None, on_delta=None, **kw):
        calls.append(1)
        return LLMResult(text="frustrated")

    monkeypatch.setattr(llm_mod, "chat", fake_chat)
    assert asyncio.run(companion.classify_mood("很生气", {"api_key": None}, user_id=999)) == "calm"
    assert calls == []


# ─── 数字分身：开关与规则录入 ──────────────────────────────────────────


def test_away_toggle_and_rule_store(db_session, user):
    """我不在 → 开启分身并引导；规则录入；我回来了 → 关闭并停用规则。"""
    from app.models import AwayRule, UserSetting

    db = db_session()

    reply = companion.try_handle_away_command(db, user, 1, "我不在")
    assert "已开启数字分身" in reply
    flag = db.query(UserSetting).filter(
        UserSetting.user_id == user.id, UserSetting.key == companion.AWAY_ON_KEY
    ).first()
    assert flag.value == "1"

    rule_text = "如果周三的会议改期，帮我改到周四"
    stored = companion.try_handle_away_command(db, user, 1, rule_text)
    assert "已记下规则" in stored
    rule = db.query(AwayRule).filter(AwayRule.user_id == user.id).one()
    assert rule.rule_text == rule_text
    assert rule.enabled == 1

    back = companion.try_handle_away_command(db, user, 1, "我回来了")
    assert "已关闭" in back
    flag = db.query(UserSetting).filter(
        UserSetting.user_id == user.id, UserSetting.key == companion.AWAY_ON_KEY
    ).first()
    assert flag.value == "0"
    rule = db.query(AwayRule).filter(AwayRule.user_id == user.id).one()
    assert rule.enabled == 0

    # 关闭后普通消息不再被当成规则拦截
    assert companion.try_handle_away_command(db, user, 1, "帮我查天气") is None


def test_away_not_intercepted_when_off(db_session, user):
    """未开启分身时，普通消息不受分身逻辑影响。"""
    db = db_session()
    assert companion.try_handle_away_command(db, user, 1, "帮我查天气") is None
    assert companion.try_handle_away_command(db, user, 1, "我回来了") is not None  # 幂等关闭


# ─── 数字分身：规则触发一次不重复 ──────────────────────────────────────


def test_rule_triggers_once_per_day(db_session, user, monkeypatch):
    """LLM 判定需要动作 → 执行并留「数字分身代劳」通知；同日再跑不重复触发。"""
    from app.models import AwayRule, Notification

    db = db_session()
    rule = AwayRule(user_id=user.id, rule_text="如果周三的会议改期，帮我改到周四", enabled=1)
    db.add(rule)
    db.commit()
    db.refresh(rule)

    need_action = [False]
    executed: list[str] = []

    async def fake_chat(messages, tools, cfg=None, on_delta=None, **kw):
        sys_text = messages[0]["content"]
        if "数字分身" in sys_text:  # 规则判定调用
            return LLMResult(text='{"need": true}' if need_action[0] else '{"need": false}')
        return LLMResult(text="calm")

    async def fake_run_agent(db_, user_, conv_id, msg, **kwargs):
        executed.append(msg)
        return "已按规则将周三的会议改期到周四", 1, []

    monkeypatch.setattr(llm_mod, "chat", fake_chat)
    monkeypatch.setattr("app.agent.engine.run_agent", fake_run_agent)

    # LLM 判定不需要动作 → 不执行、不留通知
    asyncio.run(companion.run_away_rules(db))
    assert db.query(Notification).filter(Notification.user_id == user.id).count() == 0
    assert executed == []

    # LLM 判定需要动作 → 执行并留通知
    need_action[0] = True
    asyncio.run(companion.run_away_rules(db))
    assert executed == [rule.rule_text]
    notes = db.query(Notification).filter(Notification.user_id == user.id).all()
    assert len(notes) == 1
    assert notes[0].title == "数字分身代劳"
    assert "改期" in notes[0].content

    # 同日再跑：每规则每天最多动作一次，不再重复
    asyncio.run(companion.run_away_rules(db))
    assert db.query(Notification).filter(Notification.user_id == user.id).count() == 1
    assert len(executed) == 1
