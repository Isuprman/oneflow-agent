# OneFlow 长期记忆测试：remember 工具 / 引擎注入 / /api/memories 接口
import asyncio

import pytest

from app.agent.engine import run_agent
from app.agent.llm import LLMResult
from app.models import Conversation, User, UserMemory
from app.tools.registry import execute


@pytest.fixture(autouse=True)
def _no_cloud_embedding(monkeypatch):
    """测试隔离：embedding 一律返回 None（走全量注入回退路径），不碰网络。"""

    async def _none(text, cfg):
        return None

    monkeypatch.setattr("app.agent.embed.embed_text", _none)


def _make_user(db, username="mem_user"):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------- remember 工具 ----------
def test_remember_tool_persists_memory(db_session):
    db = db_session()
    user = _make_user(db)
    result = execute("remember", {"text": "用户喜欢喝咖啡"}, user, db)
    assert result["success"] is True
    rows = db.query(UserMemory).filter(UserMemory.user_id == user.id).all()
    assert len(rows) == 1
    assert rows[0].content == "用户喜欢喝咖啡"
    db.close()


def test_remember_empty_text_fails(db_session):
    db = db_session()
    user = _make_user(db)
    result = execute("remember", {"text": "   "}, user, db)
    assert result["success"] is False
    assert "不能为空" in result["error"]
    assert db.query(UserMemory).filter(UserMemory.user_id == user.id).count() == 0
    db.close()


# ---------- 引擎注入 ----------
def test_engine_injects_memory_into_system(db_session, monkeypatch):
    db = db_session()
    user = _make_user(db, "mem_alice")
    db.add(UserMemory(user_id=user.id, content="用户喜欢喝咖啡"))
    conv = Conversation(user_id=user.id, title="t")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    captured = {}

    async def fake_chat(messages, tools, cfg=None, on_delta=None, **kwargs):
        captured["system"] = messages[0]["content"]
        return LLMResult(text="好的")

    monkeypatch.setattr("app.agent.llm.chat", fake_chat)

    reply, steps, trace = asyncio.run(run_agent(db, user, conv.id, "你好"))
    assert reply == "好的"
    assert "喜欢喝咖啡" in captured["system"]
    db.close()


# ---------- /api/memories 接口 ----------
def _register_login(client, username, password="secret123"):
    client.post("/api/auth/register", json={"username": username, "password": password})
    token = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_api_list_memories(client, db_session):
    client.post("/api/auth/register", json={"username": "api_mem", "password": "secret123"})
    db = db_session()
    user = db.query(User).filter(User.username == "api_mem").first()
    mem = UserMemory(user_id=user.id, content="用户喜欢喝咖啡")
    db.add(mem)
    db.commit()
    db.refresh(mem)
    mem_id = mem.id
    db.close()

    headers = _register_login(client, "api_mem")
    resp = client.get("/api/memories", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["content"] == "用户喜欢喝咖啡"
    assert data[0]["id"] == mem_id


def test_api_delete_memory_204(client, db_session):
    client.post("/api/auth/register", json={"username": "api_del", "password": "secret123"})
    db = db_session()
    user = db.query(User).filter(User.username == "api_del").first()
    mem = UserMemory(user_id=user.id, content="要删除的记忆")
    db.add(mem)
    db.commit()
    db.refresh(mem)
    mem_id = mem.id
    db.close()

    headers = _register_login(client, "api_del")
    resp = client.delete(f"/api/memories/{mem_id}", headers=headers)
    assert resp.status_code == 204


def test_api_delete_other_user_memory_404(client, db_session):
    client.post("/api/auth/register", json={"username": "mem_owner", "password": "secret123"})
    db = db_session()
    owner = db.query(User).filter(User.username == "mem_owner").first()
    mem = UserMemory(user_id=owner.id, content="他人的记忆")
    db.add(mem)
    db.commit()
    db.refresh(mem)
    mem_id = mem.id
    db.close()

    headers = _register_login(client, "mem_intruder")
    resp = client.delete(f"/api/memories/{mem_id}", headers=headers)
    assert resp.status_code == 404


def test_api_memories_unauthorized_401(client):
    resp = client.get("/api/memories")
    assert resp.status_code == 401
    resp = client.delete("/api/memories/1")
    assert resp.status_code == 401
