# 闲置轻推测试 — 话题优先级与去噪（mock 天气，仅测试允许）
from datetime import datetime, timedelta

from app.models import PendingAction, Schedule, User


def _login(client, username="idle_user", password="secret123"):
    client.post("/api/auth/register", json={"username": username, "password": password})
    token = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _user_id(db_session, username):
    db = db_session()
    user = db.query(User).filter(User.username == username).first()
    uid = user.id
    db.close()
    return uid


def test_confirm_topic_first(client, db_session):
    headers = _login(client)
    uid = _user_id(db_session, "idle_user")
    db = db_session()
    db.add(
        PendingAction(
            user_id=uid, conversation_id=1, tool_name="add_expense",
            arguments="{}", summary="我将为您记一笔支出：50 元",
        )
    )
    # 同时有临期日程：确认话题仍优先
    db.add(
        Schedule(user_id=uid, title="评审", start_at=datetime.now() + timedelta(minutes=10))
    )
    db.commit()
    db.close()

    resp = client.get("/api/idle-hint", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["topic"] == "confirm"
    assert "确认" in data["text"]


def test_agenda_topic_within_60min(client, db_session):
    headers = _login(client, "idle_agenda")
    uid = _user_id(db_session, "idle_agenda")
    db = db_session()
    db.add(Schedule(user_id=uid, title="产品评审", start_at=datetime.now() + timedelta(minutes=30)))
    db.commit()
    db.close()

    data = client.get("/api/idle-hint", headers=headers).json()
    assert data["topic"] == "agenda"
    assert "产品评审" in data["text"]


def test_weather_topic_when_raining(client, db_session, monkeypatch):
    headers = _login(client, "idle_rain")

    def _rain(_city, _date):
        return {"success": True, "weather": "雨", "precip_prob": 90}

    monkeypatch.setattr("app.tools.weather.query_weather", _rain)

    data = client.get("/api/idle-hint", headers=headers).json()
    # 白天有雨 → weather 话题；深夜则可能被 night 截胡，两者都接受但需非空
    assert data["topic"] in ("weather", "night")
    assert data["text"]

    # 同日第二次：天气已说过，不再重复（白天应为 null，深夜仍可能 night）
    again = client.get("/api/idle-hint", headers=headers).json()
    assert again["topic"] != "weather"


def test_nothing_to_say(client, monkeypatch):
    headers = _login(client, "idle_quiet")

    def _sunny(_city, _date):
        return {"success": True, "weather": "晴", "precip_prob": 0}

    monkeypatch.setattr("app.tools.weather.query_weather", _sunny)
    data = client.get("/api/idle-hint", headers=headers).json()
    # 白天且无话题 → 安静；深夜会给 night 问候
    assert data["topic"] in (None, "night")


def test_idle_hint_unauthed_401(client):
    assert client.get("/api/idle-hint").status_code == 401
