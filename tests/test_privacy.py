# 数据主权套包测试 — 导出结构 / purge 真删 + 用户隔离
from app.models import (
    Conversation,
    Message,
    Notification,
    ScheduledTask,
    SkillProposal,
    ToolCallLog,
    User,
    UserMemory,
    UserProfile,
)


def _register(client, username):
    client.post("/api/auth/register", json={"username": username, "password": "secret123"})
    token = client.post(
        "/api/auth/login", json={"username": username, "password": "secret123"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _uid(db, username):
    return db.query(User).filter(User.username == username).one().id


def _purge(client, headers=None, confirm="DELETE"):
    # TestClient.delete 不接收 json，统一走 request()
    return client.request("DELETE", "/api/privacy/purge", json={"confirm": confirm}, headers=headers)


def _seed_alice(client, db_session):
    headers = _register(client, "alice")
    db = db_session()
    uid = _uid(db, "alice")
    db.add(UserMemory(user_id=uid, content="喜欢喝美式"))
    db.add(UserMemory(user_id=uid, content="周一上午例会"))
    db.add(UserProfile(user_id=uid, key="city", value="上海"))
    db.add(UserProfile(user_id=uid, key="nickname", value="Alice"))
    conv = Conversation(user_id=uid, title="工作讨论")
    db.add(conv)
    db.flush()
    db.add(Message(conversation_id=conv.id, role="user", content="帮我总结一下"))
    db.add(Message(conversation_id=conv.id, role="assistant", content="好的，已总结"))
    db.add(
        ToolCallLog(
            conversation_id=conv.id,
            tool_name="summarize",
            arguments='{"n": 1}',
            result='{"ok": true}',
            success=1,
        )
    )
    db.add(
        SkillProposal(
            user_id=uid,
            slug="my_skill",
            title="数据汇总技能",
            description="把日报汇总成表格",
            status="approved",
            required_keys="{}",
        )
    )
    db.add(
        ScheduledTask(
            user_id=uid, title="晨报", instruction="跑一遍晨间简报", kind="daily", hour=8, minute=0, enabled=1
        )
    )
    db.commit()
    db.close()
    return headers


def _seed_bob(client, db_session):
    headers = _register(client, "bob")
    db = db_session()
    uid = _uid(db, "bob")
    db.add(UserMemory(user_id=uid, content="bob 的秘密"))
    conv = Conversation(user_id=uid, title="bob 会话")
    db.add(conv)
    db.flush()
    db.add(Message(conversation_id=conv.id, role="user", content="bob 的消息"))
    db.add(ScheduledTask(user_id=uid, title="bob 任务", instruction="x", kind="once", hour=9, minute=0, enabled=1))
    db.add(Notification(user_id=uid, title="bob 提醒", content="别忘收件"))
    db.commit()
    db.close()
    return headers


# ─── 导出结构 ─────────────────────────────────────────────────────────


def test_export_requires_auth(client):
    assert client.get("/api/privacy/export").status_code == 401


def test_export_structure(client, db_session):
    headers = _seed_alice(client, db_session)

    resp = client.get("/api/privacy/export", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    # 顶层结构：版本号 + 生成时间 + 五个数据分片
    assert data["format"] == "oneflow-user-export"
    assert data["version"] == 1
    assert data["generated_at"]
    assert data["user"]["username"] == "alice"
    for section in ("memories", "profile", "conversations", "skill_proposals", "tasks"):
        assert section in data

    # memories
    assert len(data["memories"]) == 2
    assert {m["content"] for m in data["memories"]} == {"喜欢喝美式", "周一上午例会"}

    # profile
    profile = {p["key"]: p["value"] for p in data["profile"]}
    assert profile == {"city": "上海", "nickname": "Alice"}

    # conversations + messages（含 tool_calls）
    assert len(data["conversations"]) == 1
    conv = data["conversations"][0]
    assert conv["title"] == "工作讨论"
    assert [m["content"] for m in conv["messages"]] == ["帮我总结一下", "好的，已总结"]
    assert conv["tool_calls"][0]["tool_name"] == "summarize"
    assert conv["tool_calls"][0]["arguments"] == {"n": 1}

    # skill_proposals
    assert len(data["skill_proposals"]) == 1
    assert data["skill_proposals"][0]["slug"] == "my_skill"
    assert data["skill_proposals"][0]["status"] == "approved"

    # tasks
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["title"] == "晨报"
    assert data["tasks"][0]["kind"] == "daily"


def test_export_empty_user(client, db_session):
    headers = _register(client, "carol")
    resp = client.get("/api/privacy/export", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["username"] == "carol"
    assert data["memories"] == []
    assert data["profile"] == []
    assert data["conversations"] == []
    assert data["skill_proposals"] == []
    assert data["tasks"] == []


# ─── purge 防误触 ─────────────────────────────────────────────────────


def test_purge_requires_confirm(client, db_session):
    headers = _seed_alice(client, db_session)

    # 不带 body → 422（请求体校验失败）
    assert client.request("DELETE", "/api/privacy/purge", headers=headers).status_code == 422
    # confirm 不对 → 400，数据保留
    resp = _purge(client, headers, confirm="no")
    assert resp.status_code == 400
    assert client.get("/api/privacy/export", headers=headers).json()["memories"]  # 仍在


def test_purge_requires_auth(client):
    assert _purge(client).status_code == 401


# ─── purge 真删 + 用户隔离 ───────────────────────────────────────────


def test_purge_deletes_all_user_data(client, db_session):
    alice_headers = _seed_alice(client, db_session)
    _seed_bob(client, db_session)
    db = db_session()
    alice_uid = _uid(db, "alice")

    resp = _purge(client, alice_headers)
    assert resp.status_code == 200
    receipt = resp.json()["receipt"]

    # 收据包含本次实际删除的各表行数
    assert receipt["user_memories"] == 2
    assert receipt["user_profiles"] == 2
    assert receipt["conversations"] == 1
    assert receipt["messages"] == 2
    assert receipt["tool_calls_log"] == 1
    assert receipt["skill_proposals"] == 1
    assert receipt["scheduled_tasks"] == 1

    # 该用户查库为空
    assert db.query(UserMemory).filter(UserMemory.user_id == alice_uid).count() == 0
    assert db.query(UserProfile).filter(UserProfile.user_id == alice_uid).count() == 0
    assert db.query(Conversation).filter(Conversation.user_id == alice_uid).count() == 0
    assert db.query(Message).count() == 1  # 只剩 bob 的
    assert db.query(SkillProposal).filter(SkillProposal.user_id == alice_uid).count() == 0
    assert db.query(ScheduledTask).filter(ScheduledTask.user_id == alice_uid).count() == 0
    db.close()

    # 导出也已清空
    export = client.get("/api/privacy/export", headers=alice_headers).json()
    assert export["memories"] == []
    assert export["profile"] == []
    assert export["conversations"] == []
    assert export["skill_proposals"] == []
    assert export["tasks"] == []


def test_purge_does_not_touch_other_users(client, db_session):
    _seed_alice(client, db_session)
    bob_headers = _seed_bob(client, db_session)
    db = db_session()
    bob_uid = _uid(db, "bob")

    # alice 已注册过，重新拿 her 的 token
    alice_token = client.post(
        "/api/auth/login", json={"username": "alice", "password": "secret123"}
    ).json()["access_token"]
    alice_headers = {"Authorization": f"Bearer {alice_token}"}
    _purge(client, alice_headers)

    # bob 的数据毫发无损
    assert db.query(UserMemory).filter(UserMemory.user_id == bob_uid).count() == 1
    assert db.query(Conversation).filter(Conversation.user_id == bob_uid).count() == 1
    assert db.query(Message).count() == 1
    assert db.query(ScheduledTask).filter(ScheduledTask.user_id == bob_uid).count() == 1
    assert db.query(Notification).filter(Notification.user_id == bob_uid).count() == 1
    db.close()

    # bob 自己的导出仍完整
    export = client.get("/api/privacy/export", headers=bob_headers).json()
    assert export["user"]["username"] == "bob"
    assert [m["content"] for m in export["memories"]] == ["bob 的秘密"]
