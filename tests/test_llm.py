# LLM 封装测试 — mock litellm.acompletion（仅测试允许 mock）
import asyncio
import json

import litellm

from app.agent.llm import chat
from app.config import settings


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
    def __init__(self, message):
        self.choices = [FakeChoice(message)]


def _run(messages, tools):
    return asyncio.run(chat(messages, tools))


def test_no_api_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "")
    res = _run([], [])
    assert res.text == "LLM 未配置：请先在「设置」页填写你自己的 LLM 密钥后使用"
    assert res.tool_call is None


def test_tool_call_parsing(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "x")

    async def fake_acompletion(**kwargs):
        return FakeResponse(
            FakeMessage(
                content=None,
                tool_calls=[FakeToolCall("get_weather", json.dumps({"city": "北京"}))],
            )
        )

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    res = _run([], [])
    assert res.text is None
    assert res.tool_call is not None
    assert res.tool_call.name == "get_weather"
    assert res.tool_call.arguments == {"city": "北京"}


def test_text_response(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "x")

    async def fake_acompletion(**kwargs):
        return FakeResponse(FakeMessage(content="你好，世界"))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    res = _run([], [])
    assert res.text == "你好，世界"
    assert res.tool_call is None
