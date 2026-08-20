# 用户画像测试 — set/get 工具 + 引擎注入 system
import asyncio

from app.agent.engine import run_agent
from app.agent.llm import LLMResult
from app.models import Conversation, User
from app.tools.profile import load_profile
from app.tools.registry import execute


def _make_user(db, username):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_set_and_get_profile(db_session):
    db = db_session()
    user = _make_user(db, "profile_user")
    result = execute("set_profile", {"key": "city", "value": "上海"}, user, db)
    assert result["success"] is True

    # 覆盖更新
    execute("set_profile", {"key": "city", "value": "北京"}, user, db)
    got = execute("get_profile", {}, user, db)
    assert got["profile"] == {"city": "北京"}
    assert load_profile(db, user.id) == {"city": "北京"}
    db.close()


def test_set_profile_rejects_unknown_key(db_session):
    db = db_session()
    user = _make_user(db, "profile_bad")
    result = execute("set_profile", {"key": "zodiac", "value": "狮子座"}, user, db)
    assert result["success"] is False
    db.close()


def test_engine_injects_profile(db_session, monkeypatch):
    db = db_session()
    user = _make_user(db, "profile_inject")
    execute("set_profile", {"key": "city", "value": "杭州"}, user, db)
    conv = Conversation(user_id=user.id, title="t")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    captured = {}

    async def fake_chat(messages, tools, cfg=None, on_delta=None):
        captured["system"] = messages[0]["content"]
        return LLMResult(text="好的")

    monkeypatch.setattr("app.agent.llm.chat", fake_chat)

    asyncio.run(run_agent(db, user, conv.id, "你好"))
    assert "用户画像" in captured["system"]
    assert "杭州" in captured["system"]
    db.close()
