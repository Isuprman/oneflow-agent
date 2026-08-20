# B2 集成测试 — 每用户配置接入 LLM 与订酒店工具（仅测试允许 mock）
import asyncio

import litellm

import app.agent.llm as llm_mod
from app.agent.llm import LLMResult
from app.config import settings
from app.models import User
from app.tools.hotel import search_hotel
from app.user_cfg import save_hotel, save_llm


# ---------- chat.py：按每用户 key 放行 ----------
def _login_headers(client, username="b2user", password="secret123") -> dict:
    client.post("/api/auth/register", json={"username": username, "password": password})
    token = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_chat_uses_user_llm_key(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "")

    headers = _login_headers(client, username="b2llm")
    resp = client.post("/api/chat/", json={"message": "hi"}, headers=headers)
    assert resp.status_code == 400
    assert "设置" in resp.json()["detail"]

    # 给该用户存 api_key 后放行
    db = db_session()
    user = db.query(User).filter(User.username == "b2llm").first()
    save_llm(db, user.id, "openai", "gpt-4o", "user-key-1", "https://api.example.com/v1")

    async def fake_chat(messages, tools, cfg=None, on_delta=None):
        return LLMResult(text="ok")

    monkeypatch.setattr(llm_mod, "chat", fake_chat)

    resp = client.post("/api/chat/", json={"message": "你好"}, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "ok"
    assert data["steps"] == 1
    db.close()


# ---------- llm.chat：cfg 覆盖全局 ----------
class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class FakeChoice:
    def __init__(self, message):
        self.message = message


class FakeResponse:
    def __init__(self, message):
        self.choices = [FakeChoice(message)]


def test_llm_chat_uses_cfg(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return FakeResponse(FakeMessage(content="你好"))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    cfg = {
        "provider": "openai",
        "model": "gpt-4o-cfg",
        "api_key": "cfg-key-123",
        "base_url": "https://cfg.example.com/v1",
    }
    res = asyncio.run(llm_mod.chat([], [], cfg))

    assert res.text == "你好"
    assert res.tool_call is None
    assert captured["model"] == "openai/gpt-4o-cfg"
    assert captured["api_key"] == "cfg-key-123"
    assert captured["api_base"] == "https://cfg.example.com/v1"


# ---------- search_hotel：每用户 cfg ----------
class FakeHotelResponse:
    def json(self):
        return {"hotels": [{"name": "测试酒店"}]}

    def raise_for_status(self):
        pass


class FakeHotelClient:
    def __init__(self, captured):
        self.captured = captured

    def get(self, url, params=None, headers=None):
        self.captured["url"] = url
        self.captured["params"] = params
        self.captured["headers"] = headers
        return FakeHotelResponse()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_hotel_uses_user_cfg(monkeypatch, db_session):
    monkeypatch.setattr(settings, "hotel_base_url", "")
    monkeypatch.setattr(settings, "hotel_api_key", "")

    db = db_session()
    user = User(username="b2hotel", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    captured = {}
    monkeypatch.setattr(
        "app.tools.hotel.httpx.Client", lambda timeout: FakeHotelClient(captured)
    )
    save_hotel(db, user.id, "https://user-hotel.example.com/search", "user-hotel-key")

    result = search_hotel({"city": "北京", "date": "2026-08-20", "budget": 500}, user, db)
    assert result["success"] is True
    assert result["raw"] == {"hotels": [{"name": "测试酒店"}]}
    assert captured["url"] == "https://user-hotel.example.com/search"
    assert captured["headers"]["Authorization"] == "Bearer user-hotel-key"
    db.close()


def test_hotel_unconfigured(monkeypatch, db_session):
    monkeypatch.setattr(settings, "hotel_base_url", "")
    monkeypatch.setattr(settings, "hotel_api_key", "")

    db = db_session()
    user = User(username="b2hotel2", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    result = search_hotel({"city": "北京"}, user, db)
    assert result["success"] is False
    assert "设置" in result["error"]
    db.close()
