# 通知路由测试 — 拉取未读 / 标记已读 / 越权防护
from app.models import Notification, User


def _register_and_login(client, username="notif_user", password="secret123"):
    client.post("/api/auth/register", json={"username": username, "password": password})
    token = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_notification(db_session, username, title, content, kind="task"):
    db = db_session()
    user = db.query(User).filter(User.username == username).first()
    note = Notification(user_id=user.id, title=title, content=content, kind=kind)
    db.add(note)
    db.commit()
    db.refresh(note)
    db.close()
    return note.id


def test_list_unread_and_mark_read(client, db_session):
    headers = _register_and_login(client)
    note_id = _seed_notification(db_session, "notif_user", "日程提醒", "15:00 您有日程：开会", "reminder")

    resp = client.get("/api/notifications", headers=headers)
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["title"] == "日程提醒"
    assert items[0]["kind"] == "reminder"

    # 标记已读后，未读列表清空
    assert client.post(f"/api/notifications/{note_id}/read", headers=headers).status_code == 204
    assert client.get("/api/notifications", headers=headers).json() == []

    # unread=false 能看到历史
    history = client.get("/api/notifications?unread=false", headers=headers).json()
    assert len(history) == 1


def test_notification_user_isolation(client, db_session):
    _register_and_login(client, username="notif_a")
    headers_b = _register_and_login(client, username="notif_b")
    note_id = _seed_notification(db_session, "notif_a", "私密播报", "只给 A 看")

    # B 看不到 A 的通知
    assert client.get("/api/notifications", headers=headers_b).json() == []
    # B 不能标记 A 的通知
    assert client.post(f"/api/notifications/{note_id}/read", headers=headers_b).status_code == 404


def test_mark_read_missing_404(client):
    headers = _register_and_login(client, username="notif_c")
    assert client.post("/api/notifications/99999/read", headers=headers).status_code == 404


def test_notifications_unauthed_401(client):
    assert client.get("/api/notifications").status_code == 401
