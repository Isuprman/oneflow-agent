# OneFlow 认证接口测试


def test_register_success(client):
    resp = client.post("/api/auth/register", json={"username": "alice", "password": "secret123"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "alice"
    assert data["id"] > 0


def test_register_duplicate_username(client):
    payload = {"username": "alice", "password": "secret123"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "用户名已存在"


def test_login_success_returns_token(client):
    client.post("/api/auth/register", json={"username": "alice", "password": "secret123"})
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "secret123"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"]
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client):
    client.post("/api/auth/register", json={"username": "alice", "password": "secret123"})
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "wrongpass"})
    assert resp.status_code == 401


def test_me_with_token(client):
    client.post("/api/auth/register", json={"username": "alice", "password": "secret123"})
    token = client.post(
        "/api/auth/login", json={"username": "alice", "password": "secret123"}
    ).json()["access_token"]
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"
