# OneFlow 每用户配置接口测试
from app import user_cfg
from app.config import settings
from app.models import User


def _headers(client) -> dict:
    client.post("/api/auth/register", json={"username": "alice", "password": "secret123"})
    token = client.post(
        "/api/auth/login", json={"username": "alice", "password": "secret123"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_llm_save_then_get(client):
    headers = _headers(client)
    resp = client.put(
        "/api/settings/llm",
        json={
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": "sk-test-123",
            "base_url": "https://api.openai.com/v1",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "openai"
    assert data["model"] == "gpt-4o"
    assert data["api_key_set"] is True
    assert data["configured"] is True

    resp = client.get("/api/settings/llm", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "openai"
    assert data["model"] == "gpt-4o"
    assert data["api_key_set"] is True
    assert data["configured"] is True
    # GET 不回传真实密钥
    assert "sk-test-123" not in resp.text
    assert "api_key" not in data


def test_llm_requires_provider_and_model(client):
    headers = _headers(client)
    resp = client.put(
        "/api/settings/llm", json={"provider": "", "model": "gpt-4o"}, headers=headers
    )
    assert resp.status_code == 400
    resp = client.put(
        "/api/settings/llm", json={"provider": "openai", "model": " "}, headers=headers
    )
    assert resp.status_code == 400


def test_hotel_not_configured_then_save(client):
    headers = _headers(client)
    resp = client.get("/api/settings/hotel", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is False
    assert data["base_url"] == ""

    resp = client.put(
        "/api/settings/hotel",
        json={"base_url": "https://hotel.example.com", "api_key": "hotel-key-1"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["base_url"] == "https://hotel.example.com"
    assert data["api_key_set"] is True
    assert data["configured"] is True

    resp = client.get("/api/settings/hotel", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["base_url"] == "https://hotel.example.com"
    assert data["api_key_set"] is True
    assert "hotel-key-1" not in resp.text


def test_get_llm_cfg_falls_back_to_global(monkeypatch, db_session):
    db = db_session()
    user = User(username="cfguser", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_model", "claude-3-5")  # 旧名，被 provider 默认覆盖
    monkeypatch.setattr(settings, "llm_api_key", "global-key")

    cfg = user_cfg.get_llm_cfg(db, user.id)
    assert cfg["provider"] == "anthropic"
    assert cfg["model"] == "claude-opus-5"
    assert cfg["api_key"] == "global-key"
    assert user_cfg.llm_configured(db, user.id) is True

    # 用户保存后覆盖全局
    user_cfg.save_llm(db, user.id, "openai", "gpt-4o", "user-key", "https://x")
    cfg = user_cfg.get_llm_cfg(db, user.id)
    assert cfg["provider"] == "openai"
    assert cfg["model"] == "gpt-4o"
    assert cfg["api_key"] == "user-key"
    db.close()


def test_get_llm_cfg_deepseek_provider_default(monkeypatch, db_session):
    db = db_session()
    user = User(username="dsuser", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    monkeypatch.setattr(settings, "llm_api_key", "global-key")
    monkeypatch.setattr(settings, "llm_base_url", "")

    cfg = user_cfg.get_llm_cfg(db, user.id)
    assert cfg["provider"] == "deepseek"
    assert cfg["model"] == "deepseek-v4-flash"
    assert cfg["base_url"] == "https://api.deepseek.com"
    assert cfg["api_key"] == "global-key"

    # Base URL 由系统按供应商自动管理：即使保存了 user base_url，也不覆盖 provider 默认
    user_cfg.save_llm(db, user.id, "deepseek", "deepseek-v4-flash", "user-key", "https://x")
    cfg = user_cfg.get_llm_cfg(db, user.id)
    assert cfg["base_url"] == "https://api.deepseek.com"
    db.close()
