# 成长日记路由测试 — 聚合字段与空库结构
from datetime import datetime

from app.models import Conversation, SkillProposal, ToolCallLog


def _register_and_login(client, username: str) -> dict:
    client.post("/api/auth/register", json={"username": username, "password": "secret123"})
    resp = client.post("/api/auth/login", json={"username": username, "password": "secret123"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _user_id(client, headers) -> int:
    return client.get("/api/auth/me", headers=headers).json()["id"]


def _seed_proposals(db_session, user_id: int) -> None:
    """1 approved（最早）+ 1 rejected（时间居中）+ 1 approved（最新）。"""
    session = db_session()
    try:
        session.add_all(
            [
                SkillProposal(
                    user_id=user_id,
                    slug="query_weather",
                    title="查询天气",
                    status="approved",
                    created_at=datetime(2026, 1, 10, 8, 30),
                ),
                SkillProposal(
                    user_id=user_id,
                    slug="bad_tool",
                    title="被拒提案",
                    status="rejected",
                    created_at=datetime(2026, 2, 1, 9, 0),
                ),
                SkillProposal(
                    user_id=user_id,
                    slug="demo_echo",
                    title="回显工具",
                    status="approved",
                    created_at=datetime(2026, 3, 5, 12, 0),
                ),
            ]
        )
        session.commit()
    finally:
        session.close()


def _seed_tool_calls(db_session, user_id: int, count: int) -> None:
    session = db_session()
    try:
        conv = Conversation(user_id=user_id, title="c")
        session.add(conv)
        session.commit()
        for i in range(count):
            session.add(
                ToolCallLog(conversation_id=conv.id, tool_name=f"tool_{i}", success=1)
            )
        session.commit()
    finally:
        session.close()


def test_journal_aggregates_fields(client, db_session):
    headers = _register_and_login(client, "jarvis_owner")
    uid = _user_id(client, headers)
    other_headers = _register_and_login(client, "someone_else")
    other_uid = _user_id(client, other_headers)

    _seed_proposals(db_session, uid)
    _seed_tool_calls(db_session, uid, count=3)
    # 其他用户的调用不应计入
    _seed_tool_calls(db_session, other_uid, count=5)

    resp = client.get("/api/journal", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["learned_count"] == 2
    assert body["rejected_count"] == 1
    assert body["total_tool_calls"] == 3

    assert body["first_skill"]["title"] == "查询天气"
    assert body["first_skill"]["date"] == "2026-01-10T08:30:00"

    titles = [m["title"] for m in body["milestones"]]
    assert titles == ["查询天气", "回显工具"]  # 全部 approved，按时间升序；rejected 不出现
    dates = [m["date"] for m in body["milestones"]]
    assert dates == ["2026-01-10T08:30:00", "2026-03-05T12:00:00"]

    # 其他用户视角：无提案、只有自己的调用数
    other_body = client.get("/api/journal", headers=other_headers).json()
    assert other_body["learned_count"] == 0
    assert other_body["total_tool_calls"] == 5


def test_journal_empty_state(client):
    headers = _register_and_login(client, "fresh_user")

    resp = client.get("/api/journal", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["first_skill"] is None
    assert body["learned_count"] == 0
    assert body["rejected_count"] == 0
    assert body["milestones"] == []
    assert body["total_tool_calls"] == 0
