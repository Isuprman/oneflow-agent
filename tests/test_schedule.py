# schedule_event / list_schedule 测试 — 使用 conftest 临时库
from datetime import datetime, timedelta

from app.models import User
from app.tools.schedule import schedule_event, list_schedule


def _make_user(db):
    user = User(username="schedule-tester", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_schedule_flow(db_session):
    db = db_session()
    user = _make_user(db)

    start = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    end = (datetime.now() + timedelta(days=1, hours=2)).strftime("%Y-%m-%d %H:%M")

    created = schedule_event({"title": "产品评审", "start_at": start, "end_at": end}, user, db)
    assert created["success"] is True
    assert created["title"] == "产品评审"
    assert created["start_at"].startswith((datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"))

    listed = list_schedule({}, user, db)
    assert listed["success"] is True
    assert any(item["title"] == "产品评审" for item in listed["items"])


def test_schedule_filter_by_date(db_session):
    db = db_session()
    user = _make_user(db)

    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    schedule_event({"title": "今天的事", "start_at": f"{today} 09:00"}, user, db)
    schedule_event({"title": "明天的事", "start_at": f"{tomorrow} 09:00"}, user, db)

    today_items = list_schedule({"date": today}, user, db)
    assert today_items["success"] is True
    titles = {item["title"] for item in today_items["items"]}
    assert "今天的事" in titles
    assert "明天的事" not in titles


def test_schedule_bad_time_format(db_session):
    db = db_session()
    user = _make_user(db)

    result = schedule_event({"title": "x", "start_at": "not-a-date"}, user, db)
    assert result["success"] is False
    assert result["error"] == "时间格式错误"
