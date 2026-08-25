# 成本仪表盘测试 — token 用量埋点落库 + 月度汇总接口
import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import litellm
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.agent.llm as llm_mod
from app.agent.llm import chat
from app.config import settings
from app.db import Base
from app.models import TokenUsage, User


# ─── 埋点单元测试（mock litellm，仅测试允许 mock）─────────────────────


class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, name, arguments):
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeChoice:
    def __init__(self, message):
        self.message = message


class FakeResponse:
    def __init__(self, message, usage=None):
        self.choices = [FakeChoice(message)]
        if usage is not None:
            self.usage = usage


class FakeDelta:
    def __init__(self, content=None):
        self.content = content


class FakeStreamChoice:
    def __init__(self, delta):
        self.delta = delta


class FakeStreamChunk:
    def __init__(self, delta=None, usage=None):
        # usage chunk 的 choices 为空，模拟 provider 末帧只带用量
        self.choices = [FakeStreamChoice(delta)] if delta is not None else []
        if usage is not None:
            self.usage = usage


@pytest.fixture()
def usage_db(monkeypatch):
    """临时库并替换 llm 模块内的 SessionLocal，让埋点落进测试库。"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(llm_mod, "SessionLocal", TestingSessionLocal)
    yield TestingSessionLocal
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    os.unlink(tmp.name)


def _rows(db_factory):
    db = db_factory()
    try:
        return db.query(TokenUsage).all()
    finally:
        db.close()


def _fake_completion(message, usage=None):
    async def fake_acompletion(**kwargs):
        return FakeResponse(message, usage=usage)

    return fake_acompletion


def _setup_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "x")


def test_chat_records_usage_with_scene_and_user(usage_db, monkeypatch):
    _setup_key(monkeypatch)
    usage = SimpleNamespace(prompt_tokens=120, completion_tokens=30)
    monkeypatch.setattr(litellm, "acompletion", _fake_completion(FakeMessage(content="你好"), usage))

    res = asyncio.run(chat(
        [{"role": "user", "content": "hi"}], [],
        scene="learn_build", user_id=42,
    ))

    assert res.error is False
    assert res.text == "你好"
    rows = _rows(usage_db)
    assert len(rows) == 1
    r = rows[0]
    assert r.scene == "learn_build"
    assert r.user_id == 42
    assert r.prompt_tokens == 120
    assert r.completion_tokens == 30


def test_chat_default_scene_is_chat(usage_db, monkeypatch):
    _setup_key(monkeypatch)
    monkeypatch.setattr(litellm, "acompletion", _fake_completion(
        FakeMessage(content="ok"),
        SimpleNamespace(prompt_tokens=7, completion_tokens=3),
    ))

    asyncio.run(chat([{"role": "user", "content": "hi"}], []))

    rows = _rows(usage_db)
    assert len(rows) == 1
    assert rows[0].scene == "chat"


def test_chat_without_usage_skips_row(usage_db, monkeypatch):
    _setup_key(monkeypatch)
    monkeypatch.setattr(litellm, "acompletion", _fake_completion(FakeMessage(content="没有用量")))

    res = asyncio.run(chat([{"role": "user", "content": "hi"}], [], scene="briefing"))

    assert res.error is False
    assert res.text == "没有用量"  # 主流程不受影响
    assert _rows(usage_db) == []


def test_usage_write_failure_does_not_break_chat(usage_db, monkeypatch):
    _setup_key(monkeypatch)
    monkeypatch.setattr(litellm, "acompletion", _fake_completion(
        FakeMessage(content="照常回复"),
        SimpleNamespace(prompt_tokens=5, completion_tokens=5),
    ))

    def broken_session():
        raise RuntimeError("db down")

    monkeypatch.setattr(llm_mod, "SessionLocal", broken_session)

    res = asyncio.run(chat([{"role": "user", "content": "hi"}], []))
    assert res.error is False
    assert res.text == "照常回复"


def test_tool_call_response_also_records(usage_db, monkeypatch):
    import json as _json

    _setup_key(monkeypatch)
    monkeypatch.setattr(litellm, "acompletion", _fake_completion(
        FakeMessage(tool_calls=[FakeToolCall("get_weather", _json.dumps({"city": "北京"}))]),
        SimpleNamespace(prompt_tokens=88, completion_tokens=12),
    ))

    res = asyncio.run(chat([{"role": "user", "content": "天气"}], []))

    assert res.tool_call is not None
    rows = _rows(usage_db)
    assert len(rows) == 1
    assert rows[0].prompt_tokens == 88


def test_stream_response_captures_final_usage_chunk(usage_db, monkeypatch):
    _setup_key(monkeypatch)

    async def fake_chunks():
        yield FakeStreamChunk(delta=FakeDelta("你"))
        yield FakeStreamChunk(delta=FakeDelta("好"))
        yield FakeStreamChunk(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4))

    async def fake_acompletion(**kwargs):  # stream=True 时 await 后拿到异步生成器
        return fake_chunks()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    res = asyncio.run(chat([{"role": "user", "content": "hi"}], [], on_delta=lambda piece: None))

    assert res.text == "你好"
    rows = _rows(usage_db)
    assert len(rows) == 1
    assert (rows[0].prompt_tokens, rows[0].completion_tokens) == (10, 4)


# ─── 路由测试（/api/usage/stats 与 monthly-summary）───────────────────


def _register_and_login(client, username="usage_user"):
    client.post("/api/auth/register", json={"username": username, "password": "secret123"})
    token = client.post(
        "/api/auth/login", json={"username": username, "password": "secret123"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_usage(db_session, username, scene, prompt, completion, created_at=None):
    db = db_session()
    user_id = db.query(User).filter(User.username == username).first().id
    row = TokenUsage(user_id=user_id, scene=scene, prompt_tokens=prompt,
                     completion_tokens=completion)
    if created_at is not None:
        row.created_at = created_at
    db.add(row)
    db.commit()
    db.close()


def test_stats_monthly_aggregation_by_scene(client, db_session):
    headers = _register_and_login(client)
    _register_and_login(client, username="usage_other")
    now = datetime.now(timezone.utc)
    _seed_usage(db_session, "usage_user", "chat", 100, 20)
    _seed_usage(db_session, "usage_user", "chat", 50, 30)
    _seed_usage(db_session, "usage_user", "learn_build", 200, 80)
    # 上月的不算、别人的不算
    _seed_usage(db_session, "usage_user", "chat", 999, 999, created_at=now - timedelta(days=45))
    _seed_usage(db_session, "usage_other", "chat", 777, 777)

    resp = client.get("/api/usage/stats", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_prompt"] == 350
    assert data["total_completion"] == 130
    scenes = {item["scene"]: item for item in data["by_scene"]}
    assert scenes["chat"] == {"scene": "chat", "prompt": 150, "completion": 50}
    assert scenes["learn_build"] == {"scene": "learn_build", "prompt": 200, "completion": 80}
    assert len(data["by_scene"]) == 2


def test_stats_empty_month_returns_zeros(client):
    headers = _register_and_login(client)
    resp = client.get("/api/usage/stats", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"total_prompt": 0, "total_completion": 0, "by_scene": []}


def test_stats_requires_auth(client):
    assert client.get("/api/usage/stats").status_code == 401
    assert client.get("/api/usage/monthly-summary").status_code == 401


def test_monthly_summary(client, db_session):
    headers = _register_and_login(client)
    _register_and_login(client, username="usage_other")
    _seed_usage(db_session, "usage_user", "chat", 120, 30)
    _seed_usage(db_session, "usage_other", "chat", 500, 500)

    resp = client.get("/api/usage/monthly-summary", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    now = datetime.now(timezone.utc)
    assert data["month"] == f"{now.year}-{now.month:02d}"
    assert data["total_prompt"] == 120
    assert data["total_completion"] == 30
    assert data["total_tokens"] == 150
    assert "150" in data["summary"]
