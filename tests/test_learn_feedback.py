# 工具反馈环测试：上线技能运行质量监控 + 自动降级 / 好评一次性通知
import asyncio

import pytest

from app.learn import habit


@pytest.fixture()
def user(db_session):
    from app.models import User

    session = db_session()
    u = User(username="feedback_user", password_hash="x")
    session.add(u)
    session.commit()
    session.refresh(u)
    uid = u.id
    session.close()
    return type("U", (), {"id": uid})()


def _setup_live_skill(db_session, user_id, slug, test_output="构建日志", n_ok=0, n_fail=0):
    """上线一个技能：approved 提案 + 语义索引行，并造近 7 天调用记录。"""
    from app.models import Conversation, LearnSkillEmbedding, SkillProposal, ToolCallLog

    session = db_session()
    try:
        p = SkillProposal(user_id=user_id, slug=slug, title=slug, description="d",
                          status="approved", tool_code="", test_code="",
                          test_output=test_output, required_keys="{}", branch="")
        session.add(p)
        session.add(LearnSkillEmbedding(user_id=user_id, slug=slug, description="d"))
        conv = Conversation(user_id=user_id, title="t")
        session.add(conv)
        session.commit()
        session.refresh(p)
        pid = p.id
        for _ in range(n_ok):
            session.add(ToolCallLog(conversation_id=conv.id, tool_name=slug,
                                    arguments="{}", success=1))
        for _ in range(n_fail):
            session.add(ToolCallLog(conversation_id=conv.id, tool_name=slug,
                                    arguments="{}", success=0))
        session.commit()
        return pid
    finally:
        session.close()


def _reload(session, model, pid):
    return session.get(model, pid)


def _notifications(session, user_id, title_part):
    from app.models import Notification

    rows = session.query(Notification).filter_by(user_id=user_id).all()
    return [n for n in rows if title_part in (n.title or "")]


def test_high_failure_rate_degrades_and_notifies(db_session, user):
    """高失败率 → proposal 置 failed + 追加反馈环日志 + 技能质量提醒通知。"""
    from app.models import SkillProposal

    slug = "get_weather"
    pid = _setup_live_skill(db_session, user.id, slug, n_fail=5)
    session = db_session()
    try:
        summaries = asyncio.run(habit.run_skill_quality_check(session))
        assert len(summaries) == 1 and "降级" in summaries[0]
        p = _reload(session, SkillProposal, pid)
        assert p.status == "failed"
        assert "[反馈环] 近7天成功率 0%，已自动降级" in p.test_output
        alerts = _notifications(session, user.id, "技能质量提醒")
        assert len(alerts) == 1
        assert "重新" in alerts[0].content  # 说明如何恢复
        # 二次运行不重复降级/通知（标记防重）
        asyncio.run(habit.run_skill_quality_check(session))
        assert len(_notifications(session, user.id, "技能质量提醒")) == 1
    finally:
        session.close()


def test_high_success_rate_praises_once(db_session, user):
    """高成功率 → 好评通知恰好一次；重复运行不再发。"""
    from app.models import SkillProposal

    slug = "calc_tool"
    pid = _setup_live_skill(db_session, user.id, slug, n_ok=10)
    session = db_session()
    try:
        summaries = asyncio.run(habit.run_skill_quality_check(session))
        assert len(summaries) == 1 and "良好" in summaries[0]
        praise = _notifications(session, user.id, "技能运行良好")
        assert len(praise) == 1
        assert slug in praise[0].title
        p = _reload(session, SkillProposal, pid)
        assert "[反馈环] 好评" in p.test_output  # 防重标记落在提案上
        assert p.status == "approved"
        # 二次运行：标记已存在 → 不再发好评
        asyncio.run(habit.run_skill_quality_check(session))
        assert len(_notifications(session, user.id, "技能运行良好")) == 1
    finally:
        session.close()


def test_below_min_calls_no_action(db_session, user):
    """不足 5 次 → 不下结论：状态不变、无任何通知。"""
    from app.models import SkillProposal

    slug = "rare_tool"
    pid = _setup_live_skill(db_session, user.id, slug, n_fail=4)  # 全失败但只有 4 次
    session = db_session()
    try:
        summaries = asyncio.run(habit.run_skill_quality_check(session))
        assert summaries == []
        p = _reload(session, SkillProposal, pid)
        assert p.status == "approved"
        assert "[反馈环]" not in p.test_output
        assert session.query(__import__("app.models", fromlist=["Notification"]).Notification).count() == 0
    finally:
        session.close()


def test_mid_rate_no_action(db_session, user):
    """50%~90% 区间既不降级也不好评。"""
    from app.models import Notification, SkillProposal

    slug = "so_so_tool"
    pid = _setup_live_skill(db_session, user.id, slug, n_ok=4, n_fail=4)  # 成功率 50%
    session = db_session()
    try:
        summaries = asyncio.run(habit.run_skill_quality_check(session))
        assert summaries == []
        assert _reload(session, SkillProposal, pid).status == "approved"
        assert session.query(Notification).count() == 0
    finally:
        session.close()
