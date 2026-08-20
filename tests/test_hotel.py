# search_hotel 测试 — 未配置报错 + 配置后 mock httpx 验证请求（每用户配置）
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User
from app.tools.hotel import search_hotel
from app.user_cfg import save_hotel


def _make_user(db: Session) -> User:
    u = User(username="hotel_tester", password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _fake_client(captured):
    class FakeResponse:
        def json(self):
            return {"hotels": [{"name": "示例酒店"}]}

        def raise_for_status(self):
            pass

    class FakeClient:
        def get(self, url, params=None, headers=None):
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            return FakeResponse()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return FakeClient()


def test_hotel_not_configured(monkeypatch, db_session):
    monkeypatch.setattr(settings, "hotel_base_url", "")
    monkeypatch.setattr(settings, "hotel_api_key", "")
    db = db_session()
    u = _make_user(db)
    result = search_hotel({"city": "北京"}, u, db)
    assert result["success"] is False
    assert "设置" in result["error"]
    db.close()


def test_hotel_success_via_user_cfg(monkeypatch, db_session):
    monkeypatch.setattr(settings, "hotel_base_url", "")
    monkeypatch.setattr(settings, "hotel_api_key", "")
    db = db_session()
    u = _make_user(db)
    save_hotel(db, u.id, "https://example.com/hotel/search", "secret-key")

    captured = {}
    monkeypatch.setattr(
        "app.tools.hotel.httpx.Client", lambda timeout: _fake_client(captured)
    )

    result = search_hotel(
        {"city": "北京", "date": "2026-08-20", "budget": 500}, u, db
    )
    assert result["success"] is True
    assert result["raw"] == {"hotels": [{"name": "示例酒店"}]}
    assert captured["url"] == "https://example.com/hotel/search"
    assert captured["params"]["city"] == "北京"
    assert captured["params"]["date"] == "2026-08-20"
    assert captured["params"]["budget"] == 500
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    db.close()


def test_hotel_success_via_global(monkeypatch, db_session):
    monkeypatch.setattr(settings, "hotel_base_url", "https://global.example/h")
    monkeypatch.setattr(settings, "hotel_api_key", "global-key")
    db = db_session()
    u = _make_user(db)

    captured = {}
    monkeypatch.setattr(
        "app.tools.hotel.httpx.Client", lambda timeout: _fake_client(captured)
    )

    result = search_hotel({"city": "上海"}, u, db)
    assert result["success"] is True
    assert captured["url"] == "https://global.example/h"
    assert captured["headers"]["Authorization"] == "Bearer global-key"
    db.close()


def test_hotel_request_failure(monkeypatch, db_session):
    monkeypatch.setattr(settings, "hotel_base_url", "https://example.com/hotel/search")
    monkeypatch.setattr(settings, "hotel_api_key", "secret-key")
    db = db_session()
    u = _make_user(db)

    class BoomClient:
        def get(self, url, params=None, headers=None):
            raise RuntimeError("connection refused")

    monkeypatch.setattr("app.tools.hotel.httpx.Client", lambda timeout: BoomClient())

    result = search_hotel({"city": "北京"}, u, db)
    assert result["success"] is False
    assert "酒店服务请求失败" in result["error"]
    db.close()
