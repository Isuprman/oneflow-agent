# 聊天 SSE 真流式接口测试 — mock LLM（仅测试允许 mock）
import asyncio
import json

import pytest

import app.agent.llm as llm_mod
from app.agent.llm import LLMResult, ToolCall
from app.config import settings

FAKE_REPLY = "这是一段比较长的测试回复用来验证分块。"


@pytest.fixture(scope="module", autouse=True)
def patch_llm_for_stream():
    """模块级：设好 LLM key，并把 agent 的 LLM 调用替换为模拟真流式的固定回复。"""
    mp = pytest.MonkeyPatch()
    mp.setattr(settings, "llm_api_key", "x")

    async def fake_chat(messages, tools, cfg=None, on_delta=None):
        # 模拟真流式：正文按 8 字分块经 on_delta 实时推出
        if on_delta is not None:
            for i in range(0, len(FAKE_REPLY), 8):
                result = on_delta(FAKE_REPLY[i : i + 8])
                if asyncio.iscoroutine(result):
                    await result
        return LLMResult(text=FAKE_REPLY)

    mp.setattr(llm_mod, "chat", fake_chat)
    yield
    mp.undo()


def _login_headers(client, username="alice", password="secret123") -> dict:
    client.post("/api/auth/register", json={"username": username, "password": password})
    token = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _parse_events(body: str) -> list[dict]:
    """解析 SSE 文本为 [{event, data}, ...]，data 为已 json.loads 的 dict。"""
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


def test_stream_delta_and_done(client):
    headers = _login_headers(client)
    resp = client.post("/api/chat/stream", json={"message": "hi"}, headers=headers)
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    events = _parse_events(resp.text)
    deltas = [e for e in events if e["event"] == "delta"]
    assert len(deltas) > 1
    assert any("测试" in e["data"]["text"] for e in deltas)

    dones = [e for e in events if e["event"] == "done"]
    assert len(dones) == 1
    done = dones[0]["data"]
    assert done["conversation_id"] > 0
    assert done["reply"] == FAKE_REPLY
    assert done["trace"] == []


def test_stream_no_key_400(client, monkeypatch):
    monkeypatch.setattr(
        "app.routers.chat_stream.llm_configured", lambda db, uid: False
    )
    headers = _login_headers(client)
    resp = client.post("/api/chat/stream", json={"message": "hi"}, headers=headers)
    assert resp.status_code == 400
    assert "LLM" in resp.json()["detail"]


def test_stream_unauthed_401(client):
    resp = client.post("/api/chat/stream", json={"message": "hi"})
    assert resp.status_code == 401


def test_stream_tool_step_events(client, monkeypatch):
    """工具调用轮：先推 step(calling) 再推 step(done)，最后 done 带完整轨迹。"""
    replies = [
        LLMResult(tool_call=ToolCall("calculate", {"expression": "(2+3)*4"})),
        LLMResult(text="结果是 20"),
    ]

    async def fake_chat(messages, tools, cfg=None, on_delta=None):
        return replies.pop(0)

    monkeypatch.setattr(llm_mod, "chat", fake_chat)
    headers = _login_headers(client, username="carol", password="secret123")
    resp = client.post("/api/chat/stream", json={"message": "算一下"}, headers=headers)
    assert resp.status_code == 200

    events = _parse_events(resp.text)
    steps = [e for e in events if e["event"] == "step"]
    assert [s["data"]["status"] for s in steps] == ["calling", "done"]
    assert steps[0]["data"]["tool"] == "calculate"
    assert steps[1]["data"]["success"] is True

    done = [e for e in events if e["event"] == "done"][0]["data"]
    assert done["reply"] == "结果是 20"
    assert len(done["trace"]) == 1


def test_stream_error_event_not_persisted(client, monkeypatch):
    """LLM 调用失败：推 error 事件，错误文本不落库进历史。"""

    async def err_chat(messages, tools, cfg=None, on_delta=None):
        return LLMResult(text="LLM 调用出错: boom", error=True)

    monkeypatch.setattr(llm_mod, "chat", err_chat)
    headers = _login_headers(client, username="dave", password="secret123")
    resp = client.post("/api/chat/stream", json={"message": "你好"}, headers=headers)
    assert resp.status_code == 200

    events = _parse_events(resp.text)
    errors = [e for e in events if e["event"] == "error"]
    assert len(errors) == 1
    assert "boom" in errors[0]["data"]["message"]

    # 后续读消息：只有 user 一条，错误回复未落库
    conv_id = [e for e in events if e["event"] == "done"][0]["data"]["conversation_id"]
    msgs = client.get(f"/api/conversations/{conv_id}/messages", headers=headers).json()
    assert [m["role"] for m in msgs] == ["user"]
