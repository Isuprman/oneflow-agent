# Agent 循环测试 — mock LLM 与外部 HTTP（天气），仅测试允许 mock
import asyncio
from datetime import datetime

from app.agent.engine import run_agent
from app.agent.llm import LLMResult, ToolCall
from app.config import settings
from app.models import Conversation, Message, ToolCallLog, User


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class FakeWeatherClient:
    """替代 httpx.Client：地理编码 + 预报 都返回固定成功结果。"""

    def get(self, url, params=None, **kwargs):
        if "geocoding" in url:
            return FakeResponse({"results": [{"latitude": 39.9, "longitude": 116.4}]})
        today = datetime.now().strftime("%Y-%m-%d")
        return FakeResponse(
            {
                "daily": {
                    "time": [today],
                    "weather_code": [0],
                    "temperature_2m_max": [30.0],
                    "temperature_2m_min": [20.0],
                    "precipitation_probability_max": [10],
                }
            }
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _new_conv(db, username):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    conv = Conversation(user_id=user.id, title="t")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return user, conv


def test_agent_loop_success(db_session, monkeypatch):
    db = db_session()
    user, conv = _new_conv(db, "agent_alice")
    monkeypatch.setattr("app.tools.weather.httpx.Client", lambda timeout: FakeWeatherClient())
    # 钉空全局 key：test_learn_b 会话级补的 key 会让 classify_mood 多消费一次
    # fake_chat 回复（情绪分类），导致本用例的回复序列错位
    monkeypatch.setattr(settings, "llm_api_key", "")

    replies = [
        LLMResult(tool_call=ToolCall("get_weather", {"city": "北京"})),
        LLMResult(text="完成"),
    ]

    async def fake_chat(messages, tools, cfg=None, on_delta=None, **kwargs):
        return replies.pop(0)

    monkeypatch.setattr("app.agent.llm.chat", fake_chat)

    reply, steps, trace = asyncio.run(run_agent(db, user, conv.id, "北京天气怎么样？"))

    assert reply == "完成"
    assert steps == 2
    assert len(trace) == 1
    assert trace[0]["tool"] == "get_weather"

    db.expire_all()
    msgs = db.query(Message).filter(Message.conversation_id == conv.id).all()
    roles = {m.role for m in msgs}
    assert {"user", "tool", "assistant"}.issubset(roles)

    logs = db.query(ToolCallLog).filter(ToolCallLog.conversation_id == conv.id).all()
    assert len(logs) == 1
    assert logs[0].tool_name == "get_weather"
    db.close()


def test_agent_loop_circuit_breaker(db_session, monkeypatch):
    db = db_session()
    user, conv = _new_conv(db, "agent_bob")
    monkeypatch.setattr("app.tools.weather.httpx.Client", lambda timeout: FakeWeatherClient())
    monkeypatch.setattr(settings, "max_steps", 2)

    async def always_tool(messages, tools, cfg=None, on_delta=None, **kwargs):
        return LLMResult(tool_call=ToolCall("get_weather", {"city": "北京"}))

    monkeypatch.setattr("app.agent.llm.chat", always_tool)

    reply, steps, trace = asyncio.run(run_agent(db, user, conv.id, "循环任务"))

    assert "已终止" in reply
    assert steps > 1
    db.close()


def test_agent_loop_llm_error_not_persisted(db_session, monkeypatch):
    """LLM 调用失败：错误文本返回给用户但不落库（不污染后续历史）。"""
    db = db_session()
    user, conv = _new_conv(db, "agent_err")

    async def err_chat(messages, tools, cfg=None, on_delta=None, **kwargs):
        return LLMResult(text="LLM 调用出错: boom", error=True)

    monkeypatch.setattr("app.agent.llm.chat", err_chat)

    events = []
    reply, steps, trace = asyncio.run(
        run_agent(db, user, conv.id, "你好", on_event=events.append)
    )

    assert "LLM 调用出错" in reply
    db.expire_all()
    msgs = db.query(Message).filter(Message.conversation_id == conv.id).all()
    # 只有 user 消息，错误回复未落库
    assert [m.role for m in msgs] == ["user"]
    # 错误事件已推送
    assert any(e.get("type") == "error" for e in events)
    db.close()
