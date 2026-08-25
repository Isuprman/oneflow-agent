# 夜间习惯→技能提案 测试
import json

import pytest

from app.learn import habit


@pytest.fixture()
def user(db_session):
    from app.models import User

    session = db_session()
    u = User(username="habit_user", password_hash="x")
    session.add(u)
    session.commit()
    session.refresh(u)
    uid = u.id
    session.close()
    return type("U", (), {"id": uid})()


def _add_tools(db_session, user_id, tool="get_weather", args='{"city":"上海"}', n=4):
    from app.models import Conversation, ToolCallLog

    session = db_session()
    try:
        conv = Conversation(user_id=user_id, title="t")
        session.add(conv)
        session.commit()
        session.refresh(conv)
        for _ in range(n):
            session.add(ToolCallLog(conversation_id=conv.id, tool_name=tool,
                                    arguments=args, success=1))
        session.commit()
    finally:
        session.close()


def test_collect_patterns_threshold(db_session, user):
    _add_tools(db_session, user.id, n=3)
    session = db_session()
    try:
        patterns = habit.collect_patterns(session, user.id)
        assert len(patterns) == 1
        assert patterns[0]["tool_name"] == "get_weather"
        assert patterns[0]["count"] == 3
        _add_tools(db_session, user.id, tool="calculate", args='{"expression":"1+1"}', n=2)
        names = [p["tool_name"] for p in habit.collect_patterns(session, user.id)]
        assert "calculate" not in names
    finally:
        session.close()


def test_run_daily_creates_proposal_and_notification(db_session, user, monkeypatch):
    from app.models import UserSetting

    _add_tools(db_session, user.id, n=4)
    session = db_session()
    for k in ("llm.provider", "llm.model", "llm.api_key"):
        session.add(UserSetting(user_id=user.id, key=k, value="test"))
    session.commit()

    class FakeResult:
        text = "把查上海天气沉淀为每日自动播报工具"
        error = False

    async def fake_chat(*a, **k):
        return FakeResult()

    monkeypatch.setattr("app.agent.llm.chat", fake_chat)

    import asyncio

    summaries = asyncio.run(habit.run_daily_proposals(session))
    assert len(summaries) == 1
    proposal = session.query(__import__("app.models", fromlist=["SkillProposal"]).SkillProposal).first()
    assert proposal is not None and proposal.status == "pending"
    assert "习惯提案" in proposal.title
    # 二次运行：pending 同名提案存在 → 不重复生成
    summaries2 = asyncio.run(habit.run_daily_proposals(session))
    assert summaries2 == []


def test_dismissed_pattern_skipped(db_session, user, monkeypatch):
    from app.models import HabitDismissed

    _add_tools(db_session, user.id, n=4)
    sig = habit.pattern_signature("get_weather", '{"city":"上海"}')
    session = db_session()
    session.add(HabitDismissed(user_id=user.id, pattern_hash=sig))
    session.commit()

    class FakeResult:
        text = "x"
        error = False

    async def fake_chat(*a, **k):
        return FakeResult()

    monkeypatch.setattr("app.agent.llm.chat", fake_chat)
    import asyncio

    summaries = asyncio.run(habit.run_daily_proposals(session))
    assert summaries == []
