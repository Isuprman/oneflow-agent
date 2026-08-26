# 记忆认知升级 测试：矛盾替换 / 重复跳过 / 补充合并 / 衰减排序 / 主题周递进
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.models import User, UserMemory
from app.tools.registry import execute


def _make_user(db, username="mem_cog_user"):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class FakeResult:
    def __init__(self, text="", error=False):
        self.text = text
        self.error = error


@pytest.fixture()
def fake_embedding(monkeypatch):
    """固定向量：任何两条文本余弦相似度 = 1.0 > 0.85，触发冲突消解/语义召回。"""
    vector = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]

    async def _embed(text, cfg):
        return vector

    monkeypatch.setattr("app.agent.embed.embed_text", _embed)
    return vector


@pytest.fixture()
def classify_chat(monkeypatch):
    """mock llm.chat：按队列顺序返回冲突判定结果，缺省判「重复」。"""
    responses = []

    async def _chat(messages, tools, cfg=None):
        text = responses.pop(0) if responses else "重复"
        return FakeResult(text=text)

    monkeypatch.setattr("app.agent.llm.chat", _chat)
    return responses


# ---------- 冲突消解：矛盾 → superseded ----------
def test_contradiction_supersedes_old(db_session, fake_embedding, classify_chat):
    db = db_session()
    user = _make_user(db, "con_user")
    try:
        first = execute("remember", {"text": "用户喜欢喝咖啡"}, user, db)
        assert first["success"] is True and first["action"] == "created"
        assert db.query(UserMemory).filter_by(user_id=user.id).count() == 1

        classify_chat.append("矛盾")
        result = execute("remember", {"text": "用户现在戒咖啡了，改喝茶"}, user, db)
        assert result["success"] is True
        assert result["action"] == "superseded"
        assert "你之前说过" in result["message"] and "已更新为" in result["message"]

        superseded = db.query(UserMemory).filter_by(user_id=user.id, status="superseded").first()
        assert superseded is not None and superseded.content == "用户喜欢喝咖啡"
        new = db.query(UserMemory).filter_by(user_id=user.id, status="active").first()
        assert new is not None and new.content == "用户现在戒咖啡了，改喝茶"
    finally:
        db.close()


# ---------- 冲突消解：重复 → 跳过不存 ----------
def test_duplicate_skipped(db_session, fake_embedding, classify_chat):
    db = db_session()
    user = _make_user(db, "dup_user")
    try:
        execute("remember", {"text": "用户喜欢喝咖啡"}, user, db)
        assert db.query(UserMemory).filter_by(user_id=user.id).count() == 1

        classify_chat.append("重复")
        result = execute("remember", {"text": "用户喜欢喝咖啡"}, user, db)
        assert result["success"] is True
        assert result["action"] == "duplicate"
        # 不新增行，旧记忆保持 active
        assert db.query(UserMemory).filter_by(user_id=user.id).count() == 1
        assert db.query(UserMemory).filter_by(user_id=user.id, status="active").count() == 1
    finally:
        db.close()


# ---------- 冲突消解：补充 → 合并文本 ----------
def test_supplement_merges_text(db_session, fake_embedding, classify_chat):
    db = db_session()
    user = _make_user(db, "sup_user")
    try:
        execute("remember", {"text": "用户喜欢喝咖啡"}, user, db)

        classify_chat.append("补充")
        result = execute("remember", {"text": "每天下午喝一杯"}, user, db)
        assert result["success"] is True
        assert result["action"] == "merged"

        row = db.query(UserMemory).filter_by(user_id=user.id).first()
        assert "喜欢喝咖啡" in row.content and "每天下午喝一杯" in row.content
        # 合并不新增行
        assert db.query(UserMemory).filter_by(user_id=user.id).count() == 1
        assert row.status == "active"
    finally:
        db.close()


# ---------- 遗忘衰减：召回排序 + 90 天低权重不再注入 + 读时更新 ----------
def test_recall_decay_order_and_stale_gate(db_session, fake_embedding):
    from app.agent.engine import _recall_memories

    db = db_session()
    user = _make_user(db, "decay_user")
    try:
        now = datetime.now(timezone.utc)
        recent = UserMemory(
            user_id=user.id, content="用户最近提到喜欢阅读",
            embedding=json.dumps(fake_embedding), last_accessed=now,
        )
        mid = UserMemory(
            user_id=user.id, content="用户六十天前说常加班",
            embedding=json.dumps(fake_embedding),
            last_accessed=now - timedelta(days=60),
        )
        stale = UserMemory(
            user_id=user.id, content="用户五百天前提过旧住址",
            embedding=json.dumps(fake_embedding),
            last_accessed=now - timedelta(days=500),
        )
        db.add_all([recent, mid, stale])
        db.commit()

        recalled = asyncio.run(_recall_memories(db, user, "聊聊阅读", {"api_key": "k"}))
        # 新的排前面、旧的排后面
        assert recalled[0] == "用户最近提到喜欢阅读"
        assert recalled[1] == "用户六十天前说常加班"
        # 500 天未访问（衰减后权重 < 阈值）→ 不再注入
        assert "用户五百天前提过旧住址" not in recalled

        # 读时更新 last_accessed：被召回的最近记忆时间被刷新
        db.refresh(recent)
        last = recent.last_accessed
        if last.tzinfo is None:  # SQLite 存储会去掉时区，按 UTC 补回
            last = last.replace(tzinfo=timezone.utc)
        assert (now - last).total_seconds() < 5
        # 未召回的过期记忆不被刷新
        db.refresh(stale)
        last_stale = stale.last_accessed
        if last_stale.tzinfo is None:
            last_stale = last_stale.replace(tzinfo=timezone.utc)
        assert (now - last_stale).days >= 499
    finally:
        db.close()


# ---------- 反向面试 2.0：主题周递进 ----------
def test_theme_progression_four_weeks(db_session, monkeypatch):
    from app.learn import interview

    db = db_session()
    u = User(username="theme_user", password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    user = type("U", (), {"id": u.id})()

    calls = []

    async def _chat(messages, tools, cfg=None):
        calls.append(messages)
        return FakeResult(text="你住在哪个城市？")

    monkeypatch.setattr("app.agent.llm.chat", _chat)
    cfg = {"api_key": "k"}

    def _setting(key):
        return interview._get_setting(db, u.id, key)

    try:
        # 第 1 周：无主题 → 自动选画像缺失维度 city
        q1 = asyncio.run(interview.generate_question(db, user, cfg))
        assert q1
        assert _setting(interview.THEME_KEY) == "city"
        assert _setting(interview.WEEK_KEY) == "1"

        # 回答 → 城市进画像
        interview.handle_answer(db, user, "我在杭州市")

        # 第 2 周：仍同主题，且题目参考上周答案（查画像/记忆）
        q2 = asyncio.run(interview.generate_question(db, user, cfg))
        assert q2
        assert _setting(interview.THEME_KEY) == "city"
        assert _setting(interview.WEEK_KEY) == "2"
        material2 = calls[-1][-1]["content"]
        assert "上次你的回答" in material2 and "杭州市" in material2

        # 第 3、4 周：主题不变，周次递增
        for week in (3, 4):
            q = asyncio.run(interview.generate_question(db, user, cfg))
            assert q
            assert _setting(interview.THEME_KEY) == "city"
            assert _setting(interview.WEEK_KEY) == str(week)

        # 第 5 周：满 4 周 → 自动换下一个缺失维度
        q5 = asyncio.run(interview.generate_question(db, user, cfg))
        assert q5
        assert _setting(interview.WEEK_KEY) == "1"
        assert _setting(interview.THEME_KEY) != "city"
    finally:
        db.close()
