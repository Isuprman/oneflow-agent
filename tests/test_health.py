# health 冒烟测试（防 settings 命名被 router 遮蔽的回归）
def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "llm_provider" in data and "llm_model" in data
