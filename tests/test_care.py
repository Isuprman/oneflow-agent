# 情景关怀测试 — 明天有雨×有日程 → 前一晚主动提醒（mock 天气查询，仅测试允许）
from datetime import datetime, timedelta

from app.models import Notification, Schedule, User
from app.scheduler import run_care_rules


def _setup(db, username, with_event=True):
    user = User(username=username, password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    if with_event:
        tomorrow = datetime.now() + timedelta(days=1)
        db.add(
            Schedule(
                user_id=user.id,
                title="产品评审",
                start_at=tomorrow.replace(hour=14, minute=0, second=0, microsecond=0),
            )
        )
        db.commit()
    return user


def _rain(_city, _date):
    return {"success": True, "weather": "雨", "precip_prob": 80, "temp_max": 25, "temp_min": 18}


def _sunny(_city, _date):
    return {"success": True, "weather": "晴", "precip_prob": 5, "temp_max": 30, "temp_min": 22}


def test_care_notifies_rain_and_event(db_session, monkeypatch):
    db = db_session()
    user = _setup(db, "care_rain")
    monkeypatch.setattr("app.tools.weather.query_weather", _rain)

    run_care_rules(db, datetime.now())

    db.expire_all()
    notes = db.query(Notification).filter(Notification.user_id == user.id).all()
    assert len(notes) == 1
    assert notes[0].kind == "care"
    assert "产品评审" in notes[0].content
    assert "带伞" in notes[0].content
    db.close()


def test_care_silent_when_sunny(db_session, monkeypatch):
    db = db_session()
    user = _setup(db, "care_sunny")
    monkeypatch.setattr("app.tools.weather.query_weather", _sunny)

    run_care_rules(db, datetime.now())

    db.expire_all()
    assert db.query(Notification).filter(Notification.user_id == user.id).count() == 0
    db.close()


def test_care_silent_when_no_event_tomorrow(db_session, monkeypatch):
    db = db_session()
    user = _setup(db, "care_noevt", with_event=False)
    monkeypatch.setattr("app.tools.weather.query_weather", _rain)

    run_care_rules(db, datetime.now())

    db.expire_all()
    assert db.query(Notification).filter(Notification.user_id == user.id).count() == 0
    db.close()


def test_care_once_per_day(db_session, monkeypatch):
    db = db_session()
    user = _setup(db, "care_dup")
    monkeypatch.setattr("app.tools.weather.query_weather", _rain)
    now = datetime.now()

    run_care_rules(db, now)
    run_care_rules(db, now)  # 同日第二次：care_last_check 拦截

    db.expire_all()
    assert db.query(Notification).filter(Notification.user_id == user.id).count() == 1
    db.close()
