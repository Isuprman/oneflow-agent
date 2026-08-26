# 影子模式测试 — 会话内实时识别重复流程并提议存为剧本
import json
import time

import pytest

import app.agent.llm as llm_mod
from app.agent.llm import LLMResult
from app.learn import shadow


@pytest.fixture(autouse=True)
def clean_tracker():
    """进程内 tracker 是模块级全局，测试间必须清空防串扰。"""
    shadow.conv_tracker.clear()
    yield
    shadow.conv_tracker.clear()


@pytest.fixture()
def user(db_session):
    from app.models import User

    session = db_session()
    u = User(username="shadow_user", password_hash="x")
    session.add(u)
    session.commit()
    session.refresh(u)
    uid = u.id
    session.close()
    return type("U", (), {"id": uid})()


def _notifications(db_session, user_id):
    from app.models import Notification

    session = db_session()
    try:
        return (
            session.query(Notification)
            .filter(Notification.user_id == user_id)
            .all()
        )
    finally:
        session.close()


def test_propose_once_within_window(db_session, user):
    """30 分钟窗口内连发 3 条 → 提议一次；继续发不重复提议。"""
    conv_id = 101
    for msg in ("帮我查上海天气", "再记一笔午饭 30 元", "顺便订个明早八点闹钟"):
        assert shadow.note_and_maybe_propose(db_session(), conv_id, user.id, msg) is None

    notes = _notifications(db_session, user.id)
    assert len(notes) == 1
    note = notes[0]
    assert note.title == "影子模式"
    # 剧本名 = 首条指令前 6 字 + 「剧本」；步骤 = 指令原文；引导语含「存为剧本」
    assert "帮我查上海天剧本" in note.content
    assert "订个明早八点闹钟" in note.content
    assert "在聊天里回复：存为剧本" in note.content

    # 已提议过 → 第 4 条不再触发
    shadow.note_and_maybe_propose(db_session(), conv_id, user.id, "再来一条")
    assert len(_notifications(db_session, user.id)) == 1


def test_no_propose_outside_window(db_session, user):
    """指令间隔超出 30 分钟窗口 → 不触发提议。"""
    conv_id = 202
    old = time.time() - 31 * 60
    shadow.conv_tracker[conv_id] = {"texts": [(old, "查天气"), (old, "记账")], "proposed": False}
    assert shadow.note_and_maybe_propose(db_session(), conv_id, user.id, "订闹钟") is None
    assert len(_notifications(db_session, user.id)) == 0
    assert shadow.conv_tracker[conv_id]["proposed"] is False


def test_confirm_scene_creates_scene_with_steps(db_session, user):
    """确认后建出 Scene：名字取首条指令、步骤齐全且按原顺序落库。"""
    from app.models import Scene

    conv_id = 303
    msgs = ["查一下上海天气", "记一笔咖啡 25 元", "设个下午三点提醒"]
    for msg in msgs:
        shadow.note_and_maybe_propose(db_session(), conv_id, user.id, msg)

    session = db_session()
    try:
        reply = shadow.confirm_scene(session, user, conv_id)
        scene = session.query(Scene).filter(Scene.user_id == user.id).one()
        assert scene.name == "查一下上海天剧本"  # 首条指令前 6 字 + 剧本
        assert [s.strip() for s in scene.steps.splitlines()] == msgs
        assert scene.enabled == 1
        assert reply == f"已创建剧本《{scene.name}》，以后说 场景 {scene.name} 一键执行"
        # 确认后 tracker 清空，重复确认不再重建
        assert conv_id not in shadow.conv_tracker
        again = shadow.confirm_scene(session, user, conv_id)
        assert "没有可存的流程记录" in again
    finally:
        session.close()


# ─── chat_stream 接线（API 级）─────────────────────────────────────────


def _login_headers(client, username="shadow_api_user", password="secret123") -> dict:
    client.post("/api/auth/register", json={"username": username, "password": password})
    token = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _parse_events(body: str) -> list[dict]:
    events = []
    for block in body.strip().split("\n\n"):
        event, data = "", ""
        for line in block.strip().splitlines():
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = line[len("data:"):].strip()
        if event:
            events.append({"event": event, "data": json.loads(data)})
    return events


def test_chat_stream_shadow_wiring(client, monkeypatch):
    """3 条消息走流式接口 → 收到影子模式通知；回「存为剧本」→ 建出剧本且不含确认指令本身。"""
    monkeypatch.setattr("app.routers.chat_stream.llm_configured", lambda db, uid: True)

    async def fake_chat(messages, tools, cfg=None, on_delta=None):
        return LLMResult(text="好的")

    monkeypatch.setattr(llm_mod, "chat", fake_chat)
    headers = _login_headers(client)

    conv_id = None
    for msg in ("查天气", "记一笔账", "定个提醒"):
        payload = {"message": msg} if conv_id is None else {"message": msg, "conversation_id": conv_id}
        resp = client.post("/api/chat/stream", json=payload, headers=headers)
        assert resp.status_code == 200
        done = [e for e in _parse_events(resp.text) if e["event"] == "done"][0]["data"]
        conv_id = done["conversation_id"]

    notes = client.get("/api/notifications?unread=true", headers=headers).json()
    shadow_notes = [n for n in notes if n["title"] == "影子模式"]
    assert len(shadow_notes) == 1
    assert "在聊天里回复：存为剧本" in shadow_notes[0]["content"]

    resp = client.post(
        "/api/chat/stream",
        json={"message": "存为剧本", "conversation_id": conv_id},
        headers=headers,
    )
    done = [e for e in _parse_events(resp.text) if e["event"] == "done"][0]["data"]
    assert "已创建剧本" in done["reply"]

    scenes = client.get("/api/scenes", headers=headers).json()
    assert len(scenes) == 1
    assert scenes[0]["steps"] == ["查天气", "记一笔账", "定个提醒"]
