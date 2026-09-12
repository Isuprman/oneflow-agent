# 聊天接口测试 — mock LLM（仅测试允许 mock）
import pytest

import app.agent.llm as llm_mod
from app.agent.llm import LLMResult
from app.config import settings


@pytest.fixture(scope="module", autouse=True)
def patch_llm_for_chat():
    """模块级：设好 LLM key，并把 agent 的 LLM 调用替换为返回固定文本。"""
    mp = pytest.MonkeyPatch()
    mp.setattr(settings, "llm_api_key", "x")

    async def fake_chat(messages, tools, cfg=None, on_delta=None, **kwargs):
        return LLMResult(text="你好")

    mp.setattr(llm_mod, "chat", fake_chat)
    yield
    mp.undo()


def _login_headers(client, username="alice", password="secret123") -> dict:
    client.post("/api/auth/register", json={"username": username, "password": password})
    token = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_chat_no_api_key_400(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "")
    headers = _login_headers(client)
    resp = client.post("/api/chat/", json={"message": "hi"}, headers=headers)
    assert resp.status_code == 400
    assert "LLM" in resp.json()["detail"]


def test_chat_creates_conversation(client):
    headers = _login_headers(client)
    resp = client.post("/api/chat/", json={"message": "你好"}, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["conversation_id"] > 0
    assert data["reply"] == "你好"
    assert data["steps"] == 1
    assert data["trace"] == []

    convs = client.get("/api/conversations/", headers=headers).json()
    assert any(c["id"] == data["conversation_id"] for c in convs)


def test_chat_other_users_conversation_404(client):
    alice_headers = _login_headers(client)
    conv_id = client.post(
        "/api/chat/", json={"message": "你好"}, headers=alice_headers
    ).json()["conversation_id"]

    bob_headers = _login_headers(client, username="bob", password="secret123")
    resp = client.post(
        "/api/chat/",
        json={"conversation_id": conv_id, "message": "hi"},
        headers=bob_headers,
    )
    assert resp.status_code == 404
