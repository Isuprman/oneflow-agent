# 晨间简报路由测试 — 一键预置/关闭每日简报任务
from app.models import ScheduledTask, User
from app.routers.briefing import BRIEFING_TITLE


def _login_headers(client, username="brief_user", password="secret123"):
    client.post("/api/auth/register", json={"username": username, "password": password})
    token = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_briefing_enable_creates_daily_task(client, db_session):
    headers = _login_headers(client)
    resp = client.put("/api/briefing", json={"enabled": True, "hour": 7, "minute": 30}, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"enabled": True, "hour": 7, "minute": 30}

    db = db_session()
    user = db.query(User).filter(User.username == "brief_user").first()
    tasks = db.query(ScheduledTask).filter(ScheduledTask.user_id == user.id).all()
    assert len(tasks) == 1
    assert tasks[0].title == BRIEFING_TITLE
    assert tasks[0].kind == "daily"
    assert tasks[0].hour == 7 and tasks[0].minute == 30
    assert tasks[0].enabled == 1
    db.close()

    # GET 反映开启状态
    got = client.get("/api/briefing", headers=headers)
    assert got.json()["enabled"] is True


def test_briefing_update_reuses_task(client, db_session):
    headers = _login_headers(client, username="brief_upd")
    client.put("/api/briefing", json={"enabled": True, "hour": 8, "minute": 0}, headers=headers)
    client.put("/api/briefing", json={"enabled": True, "hour": 6, "minute": 15}, headers=headers)

    db = db_session()
    user = db.query(User).filter(User.username == "brief_upd").first()
    tasks = db.query(ScheduledTask).filter(ScheduledTask.user_id == user.id).all()
    # 仍是同一个任务，只是改了时间
    assert len(tasks) == 1
    assert tasks[0].hour == 6 and tasks[0].minute == 15
    db.close()


def test_briefing_disable(client, db_session):
    headers = _login_headers(client, username="brief_off")
    client.put("/api/briefing", json={"enabled": True, "hour": 9, "minute": 0}, headers=headers)
    resp = client.put("/api/briefing", json={"enabled": False}, headers=headers)
    assert resp.json()["enabled"] is False

    db = db_session()
    user = db.query(User).filter(User.username == "brief_off").first()
    task = db.query(ScheduledTask).filter(ScheduledTask.user_id == user.id).first()
    assert task is not None and task.enabled == 0
    db.close()

    assert client.get("/api/briefing", headers=headers).json()["enabled"] is False


def test_briefing_unauthed_401(client):
    assert client.get("/api/briefing").status_code == 401
