# 定时任务管理路由测试 — 列表排除晨间简报 / 启停 / 删除 / 简报保护
from datetime import datetime, timedelta

from app.models import ScheduledTask, User
from app.routers.briefing import BRIEFING_TITLE


def _login(client, username="task_user", password="secret123"):
    client.post("/api/auth/register", json={"username": username, "password": password})
    token = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_task(db_session, username, title="喝水提醒", kind="daily"):
    db = db_session()
    user = db.query(User).filter(User.username == username).first()
    task = ScheduledTask(
        user_id=user.id,
        title=title,
        instruction="提醒我喝水",
        kind=kind,
        hour=21,
        minute=0,
        enabled=1,
        next_run_at=datetime.now() + timedelta(hours=1),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    db.close()
    return task.id


def test_list_excludes_briefing(client, db_session):
    headers = _login(client)
    db = db_session()
    user = db.query(User).filter(User.username == "task_user").first()
    db.add(
        ScheduledTask(
            user_id=user.id, title=BRIEFING_TITLE, instruction="x", kind="daily",
            hour=8, minute=0, enabled=1, next_run_at=datetime.now() + timedelta(hours=1),
        )
    )
    db.commit()
    db.close()
    task_id = _seed_task(db_session, "task_user")

    resp = client.get("/api/tasks", headers=headers)
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == task_id
    assert items[0]["kind_label"] == "每天"
    assert all(item["title"] != BRIEFING_TITLE for item in items)


def test_toggle_task_off_and_on(client, db_session):
    headers = _login(client, "task_toggle")
    task_id = _seed_task(db_session, "task_toggle")

    off = client.put(f"/api/tasks/{task_id}", json={"enabled": False}, headers=headers)
    assert off.status_code == 200 and off.json()["enabled"] is False

    on = client.put(f"/api/tasks/{task_id}", json={"enabled": True}, headers=headers)
    assert on.status_code == 200 and on.json()["enabled"] is True
    assert on.json()["next_run_at"] is not None


def test_delete_task(client, db_session):
    headers = _login(client, "task_del")
    task_id = _seed_task(db_session, "task_del")
    assert client.delete(f"/api/tasks/{task_id}", headers=headers).status_code == 204
    assert client.get("/api/tasks", headers=headers).json() == []
    # 再删一次 404
    assert client.delete(f"/api/tasks/{task_id}", headers=headers).status_code == 404


def test_briefing_task_protected(client, db_session):
    headers = _login(client, "task_brief")
    db = db_session()
    user = db.query(User).filter(User.username == "task_brief").first()
    brief = ScheduledTask(
        user_id=user.id, title=BRIEFING_TITLE, instruction="x", kind="daily",
        hour=8, minute=0, enabled=1, next_run_at=datetime.now() + timedelta(hours=1),
    )
    db.add(brief)
    db.commit()
    db.refresh(brief)
    db.close()

    assert client.put(f"/api/tasks/{brief.id}", json={"enabled": False}, headers=headers).status_code == 400
    assert client.delete(f"/api/tasks/{brief.id}", headers=headers).status_code == 400


def test_other_user_task_isolated(client, db_session):
    _login(client, "task_owner")
    task_id = _seed_task(db_session, "task_owner")
    other_headers = _login(client, "task_stranger")
    assert client.delete(f"/api/tasks/{task_id}", headers=other_headers).status_code == 404
