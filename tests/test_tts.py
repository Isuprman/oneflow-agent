# TTS 接口测试 — mock edge_tts（仅测试允许 mock）
import sys
import types

import pytest


def _login_headers(client, username="alice", password="secret123") -> dict:
    client.post("/api/auth/register", json={"username": username, "password": password})
    token = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class FakeComm:
    def __init__(self, text, voice):
        self.text = text
        self.voice = voice

    async def stream(self):
        yield {"type": "audio", "data": b"fakeaudio"}


@pytest.fixture()
def patch_edge_tts(monkeypatch):
    """edge_tts 在路由函数内 import，无法直接用 dotted-path 打补丁，
    改为替换 sys.modules 里的 edge_tts 模块。"""
    fake_module = types.ModuleType("edge_tts")
    fake_module.Communicate = FakeComm
    monkeypatch.setitem(sys.modules, "edge_tts", fake_module)


def test_tts_success(client, patch_edge_tts):
    headers = _login_headers(client)
    resp = client.post("/api/tts", json={"text": "你好"}, headers=headers)
    assert resp.status_code == 200
    assert "audio" in resp.headers["content-type"]
    assert resp.content == b"fakeaudio"


def test_tts_empty_text_400(client, patch_edge_tts):
    headers = _login_headers(client)
    resp = client.post("/api/tts", json={"text": "   "}, headers=headers)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "文本不能为空"


def test_tts_text_too_long_400(client, patch_edge_tts):
    headers = _login_headers(client)
    resp = client.post("/api/tts", json={"text": "啊" * 2001}, headers=headers)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "文本过长"


def test_tts_requires_auth(client):
    resp = client.post("/api/tts", json={"text": "你好"})
    assert resp.status_code == 401
