# 技能链测试：保存/列表/删除 / 顺序执行与 {{上一步}} 插值 / 嵌套防护 / 隔离
import pytest

from app.models import Conversation, User
from app.tools import chains
from app.tools.registry import execute


def _make_user(db, username="chain_user"):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(autouse=True)
def _clear_running_flag():
    chains._RUNNING.clear()
    yield
    chains._RUNNING.clear()


def test_save_list_delete_chain(db_session):
    db = db_session()
    user = _make_user(db)
    result = execute(
        "save_skill_chain",
        {"name": "雨天流程", "description": "查雨并提醒", "steps": ["查明天天气", "若有雨：提醒带伞 {{上一步}}"]},
        user,
        db,
    )
    assert result["success"] is True

    listing = execute("list_skill_chains", {}, user, db)
    assert listing["chains"][0]["name"] == "雨天流程"
    assert listing["chains"][0]["steps"][1].endswith("{{上一步}}")

    result = execute("delete_skill_chain", {"name": "雨天流程"}, user, db)
    assert result["success"] is True
    assert execute("list_skill_chains", {}, user, db)["chains"] == []
    db.close()


def test_save_duplicate_and_cap(db_session):
    db = db_session()
    user = _make_user(db)
    execute("save_skill_chain", {"name": "链A", "steps": ["s1"]}, user, db)
    dup = execute("save_skill_chain", {"name": "链A", "steps": ["s2"]}, user, db)
    assert dup["success"] is False and "已存在同名" in dup["error"]

    capped = execute("save_skill_chain", {"name": "链B", "steps": [f"s{i}" for i in range(8)]}, user, db)
    assert capped["success"] is False and "6" in capped["error"]
    db.close()


def test_run_chain_executes_in_order_with_substitution(db_session, monkeypatch):
    db = db_session()
    user = _make_user(db)
    conv = Conversation(user_id=user.id, title="技能链：雨天流程")
    db.add(conv)
    db.commit()
    execute(
        "save_skill_chain",
        {"name": "雨天流程", "steps": ["查明天天气", "根据「{{上一步}}」提醒带伞"]},
        user,
        db,
    )

    calls: list[str] = []

    async def fake_run_agent(db_, user_, conv_id, msg, **kw):
        calls.append(msg)
        return f"回复#{len(calls)}", 1, []

    monkeypatch.setattr("app.agent.engine.run_agent", fake_run_agent)
    result = execute("run_skill_chain", {"name": "雨天流程"}, user, db)
    assert result["success"] is True
    assert len(result["steps"]) == 2
    assert calls[0] == "查明天天气"
    assert calls[1] == "根据「回复#1」提醒带伞"  # {{上一步}} 被上一步回复替换
    db.close()


def test_run_chain_missing_or_disabled(db_session):
    db = db_session()
    user = _make_user(db)
    missing = execute("run_skill_chain", {"name": "不存在的链"}, user, db)
    assert missing["success"] is False
    db.close()


def test_run_chain_nested_blocked(db_session, monkeypatch):
    db = db_session()
    user = _make_user(db)
    conv = Conversation(user_id=user.id, title="技能链：嵌套链")
    db.add(conv)
    db.commit()
    execute("save_skill_chain", {"name": "嵌套链", "steps": ["s1"]}, user, db)

    def fake_run_agent(db_, user_, conv_id, msg, **kw):
        # 链执行中再次触发自身 → 应被嵌套防护拒绝
        nested = execute("run_skill_chain", {"name": "嵌套链"}, user_, db_)
        assert nested["success"] is False and "嵌套" in nested["error"]
        return "ok", 1, []

    monkeypatch.setattr("app.agent.engine.run_agent", fake_run_agent)
    result = execute("run_skill_chain", {"name": "嵌套链"}, user, db)
    assert result["success"] is True
    db.close()


def test_run_chain_user_isolation(db_session):
    db = db_session()
    owner = _make_user(db, "chain_owner")
    execute("save_skill_chain", {"name": "私有链", "steps": ["s1"]}, owner, db)
    intruder = _make_user(db, "chain_intruder")
    result = execute("run_skill_chain", {"name": "私有链"}, intruder, db)
    assert result["success"] is False
    db.close()
