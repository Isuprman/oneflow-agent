# 情境剧本测试 — CRUD / 顺序执行且单步失败不中断（monkeypatch run_agent）/ 同名拒绝
import json

import app.routers.chat_stream as chat_stream_router
import app.routers.scenes as scenes_router
from app.config import settings


def _login_headers(client, username="alice", password="secret123") -> dict:
    client.post("/api/auth/register", json={"username": username, "password": password})
    token = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create(client, headers, name="出差", steps=None) -> dict:
    payload_steps = steps if steps is not None else ["查天气", "看日程"]
    return client.post(
        "/api/scenes",
        json={"name": name, "steps": payload_steps},
        headers=headers,
    )


def test_scenes_require_auth(client):
    assert client.get("/api/scenes").status_code == 401
    assert client.post("/api/scenes", json={"name": "x", "steps": ["y"]}).status_code == 401


def test_scene_crud(client):
    headers = _login_headers(client)
    # 空列表
    assert client.get("/api/scenes", headers=headers).json() == []
    # 创建：数组转按行存储
    resp = _create(client, headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "出差"
    assert data["steps"] == ["查天气", "看日程"]
    assert data["step_count"] == 2
    assert data["enabled"] is True
    # 列表
    rows = client.get("/api/scenes", headers=headers).json()
    assert len(rows) == 1
    assert rows[0]["id"] == data["id"]
    # 启停
    sid = data["id"]
    off = client.put(f"/api/scenes/{sid}", json={"enabled": False}, headers=headers).json()
    assert off["enabled"] is False
    on = client.put(f"/api/scenes/{sid}", json={"enabled": True}, headers=headers).json()
    assert on["enabled"] is True
    # 删除
    assert client.delete(f"/api/scenes/{sid}", headers=headers).status_code == 204
    assert client.get("/api/scenes", headers=headers).json() == []
    # 不存在/越权 → 404
    assert client.put("/api/scenes/9999", json={"enabled": True}, headers=headers).status_code == 404
    assert client.delete("/api/scenes/9999", headers=headers).status_code == 404


def test_scene_create_validation(client):
    headers = _login_headers(client)
    assert _create(client, headers, name="  ").status_code == 400
    assert _create(client, headers, steps=[]).status_code == 400
    assert _create(client, headers, steps=[f"步骤{i}" for i in range(11)]).status_code == 400


def test_scene_run_sequential_and_failure_tolerant(client, monkeypatch):
    headers = _login_headers(client)
    created = _create(client, headers).json()
    calls: list[str] = []

    async def fake_run_agent(db, user, conv_id, user_msg, on_event=None, stream=False):
        calls.append(user_msg)
        if user_msg == "查天气":
            raise RuntimeError("boom")
        return f"回复:{user_msg}", 1, []

    monkeypatch.setattr(scenes_router, "run_agent", fake_run_agent)
    resp = client.post(f"/api/scenes/{created['id']}/run", headers=headers)
    assert resp.status_code == 200
    results = resp.json()
    # 顺序执行：两条指令都喂给了 agent
    assert calls == ["查天气", "看日程"]
    # 单步失败不中断：第一步行失败，第二步行成功
    assert [r["step"] for r in results] == ["查天气", "看日程"]
    assert results[0]["success"] is False
    assert "boom" in results[0]["reply"]
    assert results[1]["success"] is True
    assert results[1]["reply"] == "回复:看日程"


def test_scene_run_disabled_rejected(client):
    headers = _login_headers(client)
    created = _create(client, headers).json()
    client.put(f"/api/scenes/{created['id']}", json={"enabled": False}, headers=headers)
    resp = client.post(f"/api/scenes/{created['id']}/run", headers=headers)
    assert resp.status_code == 400
    assert "未启用" in resp.json()["detail"]


def test_scene_duplicate_name_rejected(client):
    headers = _login_headers(client)
    assert _create(client, headers, name="同名").status_code == 200
    assert _create(client, headers, name="同名").status_code == 409
    # 用户隔离：另一个用户可建同名
    headers2 = _login_headers(client, username="bob", password="secret123")
    assert _create(client, headers2, name="同名").status_code == 200


# ─── 聊天「场景 xxx」前缀钩子 ─────────────────────────────────────

def _parse_sse(body: str) -> list[dict]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.strip().splitlines()
        if not lines:
            continue
        event, data = "", ""
        for line in lines:
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = line[len("data:"):].strip()
        if event:
            events.append({"event": event, "data": json.loads(data)})
    return events


def test_chat_stream_scene_prefix(client, monkeypatch):
    """聊天发「场景 出差」：命中启用剧本 → 逐条喂 agent 并把结果拼成回复流式推送。"""
    monkeypatch.setattr(settings, "llm_api_key", "x")
    headers = _login_headers(client)
    created = _create(client, headers).json()  # 出差: 查天气 / 看日程
    calls: list[str] = []

    async def fake_run_agent(db, user, conv_id, user_msg, on_event=None, stream=False):
        calls.append(user_msg)
        return f"回复:{user_msg}", 1, []

    monkeypatch.setattr(chat_stream_router, "run_agent", fake_run_agent)
    resp = client.post("/api/chat/stream", json={"message": "场景 出差"}, headers=headers)
    assert resp.status_code == 200
    assert calls == ["查天气", "看日程"]
    done = [e for e in _parse_sse(resp.text) if e["event"] == "done"][0]["data"]
    assert done["conversation_id"] > 0
    assert done["reply"] == "回复:查天气\n\n回复:看日程"
    assert done["steps"] == 2
    # 会话标题是「场景 · 出差」而非消息前 20 字
    convs = client.get("/api/conversations", headers=headers).json()
    assert any(c["title"] == f"场景 · {created['name']}" for c in convs)


def test_chat_stream_scene_prefix_no_match_falls_through(client, monkeypatch):
    """无同名剧本：原样放行走 agent（run_agent 收到原始消息）。"""
    monkeypatch.setattr(settings, "llm_api_key", "x")
    headers = _login_headers(client)
    calls: list[str] = []

    async def fake_run_agent(db, user, conv_id, user_msg, on_event=None, stream=False):
        calls.append(user_msg)
        return "普通回复", 1, []

    monkeypatch.setattr(chat_stream_router, "run_agent", fake_run_agent)
    resp = client.post("/api/chat/stream", json={"message": "场景 不存在剧本"}, headers=headers)
    assert resp.status_code == 200
    assert calls == ["场景 不存在剧本"]
