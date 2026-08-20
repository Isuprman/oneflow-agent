# OneFlow 会话接口测试
from app.models import Message, ToolCallLog


def _login_headers(client) -> dict:
    client.post("/api/auth/register", json={"username": "alice", "password": "secret123"})
    token = client.post(
        "/api/auth/login", json={"username": "alice", "password": "secret123"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_conversation(client):
    headers = _login_headers(client)
    resp = client.post("/api/conversations/", json={"title": "hello"}, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] > 0
    assert data["title"] == "hello"


def test_list_conversations_desc(client):
    headers = _login_headers(client)
    client.post("/api/conversations/", json={"title": "first"}, headers=headers)
    client.post("/api/conversations/", json={"title": "second"}, headers=headers)
    resp = client.get("/api/conversations/", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["title"] == "second"
    assert data[0]["id"] > data[1]["id"]


def test_messages_after_insert(client, db_session):
    headers = _login_headers(client)
    conv = client.post("/api/conversations/", json={}, headers=headers).json()
    db = db_session()
    db.add(Message(conversation_id=conv["id"], role="user", content="hi"))
    db.commit()
    db.close()
    resp = client.get(f"/api/conversations/{conv['id']}/messages", headers=headers)
    assert resp.status_code == 200
    msgs = resp.json()
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "hi"


def test_trace_empty(client):
    headers = _login_headers(client)
    conv = client.post("/api/conversations/", json={}, headers=headers).json()
    resp = client.get(f"/api/conversations/{conv['id']}/trace", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_trace_with_tool_logs(client, db_session):
    headers = _login_headers(client)
    conv = client.post("/api/conversations/", json={}, headers=headers).json()
    db = db_session()
    db.add(
        ToolCallLog(
            conversation_id=conv["id"],
            tool_name="weather",
            arguments='{"city": "sh"}',
            result='{"temp": 20}',
            success=1,
        )
    )
    db.commit()
    db.close()
    resp = client.get(f"/api/conversations/{conv['id']}/trace", headers=headers)
    assert resp.status_code == 200
    steps = resp.json()
    assert len(steps) == 1
    assert steps[0]["tool"] == "weather"
    assert steps[0]["arguments"] == {"city": "sh"}
    assert steps[0]["result"] == {"temp": 20}
    assert steps[0]["success"] is True


def test_delete_conversation(client):
    headers = _login_headers(client)
    conv = client.post("/api/conversations/", json={}, headers=headers).json()
    resp = client.delete(f"/api/conversations/{conv['id']}", headers=headers)
    assert resp.status_code == 204
    resp = client.get("/api/conversations/", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_other_users_conversation_404(client):
    headers = _login_headers(client)
    conv = client.post("/api/conversations/", json={}, headers=headers).json()
    # 第二个用户看不到第一个用户的会话
    client.post("/api/auth/register", json={"username": "bob", "password": "secret123"})
    bob_token = client.post(
        "/api/auth/login", json={"username": "bob", "password": "secret123"}
    ).json()["access_token"]
    bob_headers = {"Authorization": f"Bearer {bob_token}"}
    resp = client.get(f"/api/conversations/{conv['id']}/messages", headers=bob_headers)
    assert resp.status_code == 404
    resp = client.delete(f"/api/conversations/{conv['id']}", headers=bob_headers)
    assert resp.status_code == 404
