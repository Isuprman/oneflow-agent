# 反向面试 测试：周内节流 / 生成问题并入通知 / 回答写入画像或记忆
import asyncio

import pytest

from app.learn import interview


@pytest.fixture()
def user(db_session):
    from app.models import User

    session = db_session()
    u = User(username="interview_user", password_hash="x")
    session.add(u)
    session.commit()
    session.refresh(u)
    uid = u.id
    session.close()
    return type("U", (), {"id": uid})()


class FakeResult:
    def __init__(self, text="你最近常查天气，是喜欢清晨的空气还是傍晚的风？", error=False):
        self.text = text
        self.error = error


@pytest.fixture()
def fake_chat(monkeypatch):
    """mock llm.chat：返回固定的自然提问。"""
    calls = []

    async def _chat(messages, tools, cfg=None):
        calls.append({"messages": messages, "tools": tools})
        return FakeResult()

    monkeypatch.setattr("app.agent.llm.chat", _chat)
    return calls


def test_should_interview_once_per_week(db_session, user):
    from datetime import date, timedelta

    from app.models import UserSetting

    session = db_session()
    try:
        # 首次：从未问过 → 允许
        assert interview.should_interview(session, user.id) is True
        # 周内已问过（6 天前）→ 不再触发
        session.add(UserSetting(user_id=user.id, key=interview.LAST_ASKED_KEY,
                                value=(date.today() - timedelta(days=6)).isoformat()))
        session.commit()
        assert interview.should_interview(session, user.id) is False
        # 满 7 天 → 再次允许
        row = session.query(UserSetting).filter_by(user_id=user.id, key=interview.LAST_ASKED_KEY).first()
        row.value = (date.today() - timedelta(days=7)).isoformat()
        session.commit()
        assert interview.should_interview(session, user.id) is True
    finally:
        session.close()


def test_generate_and_deliver_creates_notification(db_session, user, fake_chat):
    from app.models import Notification

    session = db_session()
    try:
        question = asyncio.run(interview.generate_question(session, user, {"api_key": "k"}))
        assert question and "天气" in question
        # 素材转纯文本提问，不带工具
        assert fake_chat[0]["tools"] == []
        interview.deliver(session, user.id, question)
        notification = (
            session.query(Notification)
            .filter(Notification.user_id == user.id, Notification.title == "贾维斯想更了解你")
            .first()
        )
        assert notification is not None
        assert question in notification.content
        assert "面试 " in notification.content
        # 投递即标记本周已问 → should_interview 转为 False
        assert interview.should_interview(session, user.id) is False
    finally:
        session.close()


def test_handle_answer_writes_profile_or_memory(db_session, user):
    from app.models import UserMemory, UserProfile

    session = db_session()
    try:
        # 城市类回答 → 进画像
        thanks_city = interview.handle_answer(session, user, "我在杭州市")
        profile = session.query(UserProfile).filter_by(user_id=user.id, key="city").first()
        assert profile is not None and profile.value == "杭州市"
        assert "谢谢" in thanks_city and "杭州" in thanks_city
        # 其余回答 → 进长期记忆
        thanks_memory = interview.handle_answer(session, user, "我最喜欢在深夜写代码")
        memory = session.query(UserMemory).filter_by(user_id=user.id).first()
        assert memory is not None and memory.content == "我最喜欢在深夜写代码"
        assert "谢谢" in thanks_memory
        # 直辖市裸名也识别为城市
        interview.handle_answer(session, user, "上海")
        profile = session.query(UserProfile).filter_by(user_id=user.id, key="city").first()
        assert profile.value == "上海"
    finally:
        session.close()
