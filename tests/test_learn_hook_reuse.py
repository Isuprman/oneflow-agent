# 聊天钩子复用检查测试 — 相似度高的已学技能直接复用，不重复构建（构建器/检索全桩化）
from types import SimpleNamespace

import pytest

from app.learn import hook, service


@pytest.fixture(autouse=True)
def _clean_pending():
    """pending_intents 是进程内全局态，用例间互不留痕。"""
    yield
    hook.pending_intents.clear()


def _register_and_login(client) -> dict:
    client.post("/api/auth/register", json={"username": "reuser1", "password": "secret123"})
    resp = client.post("/api/auth/login", json={"username": "reuser1", "password": "secret123"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _setup_llm_config(db_session, user_id: int) -> None:
    from app.models import UserSetting

    session = db_session()
    try:
        for key in ("llm.provider", "llm.model", "llm.api_key"):
            session.add(UserSetting(user_id=user_id, key=key, value="test"))
        session.commit()
    finally:
        session.close()


def _fake_proposal() -> SimpleNamespace:
    return SimpleNamespace(
        id=101, slug="query_express_v2", title="查快递增强版",
        status="pending", required_keys="{}", test_output="",
    )


async def _identity_correct(text, cfg):
    return text


@pytest.fixture()
def stubs(monkeypatch):
    """统一桩件：ASR 纠错原样返回；检索结果可注入；构建器记录调用。"""
    monkeypatch.setattr("app.learn.hook.correct_asr_text", _identity_correct)
    state = {"similar": [], "built_raws": []}

    async def fake_search(db, user_id, query_text, cfg, top_k=3):
        return state["similar"][:top_k]

    def fake_build(db, user, raw, cfg):
        state["built_raws"].append(raw)
        return _fake_proposal()

    monkeypatch.setattr("app.learn.retrieval.search_similar", fake_search)
    monkeypatch.setattr(service, "build_proposal", fake_build)
    return state


def test_high_score_offers_reuse_without_rebuild(client, db_session, stubs):
    headers = _register_and_login(client)
    uid_row = client.get("/api/auth/me", headers=headers).json()
    _setup_llm_config(db_session, uid_row["id"])
    stubs["similar"] = [{"slug": "query_express", "description": "查快递技能", "score": 0.92}]

    resp = client.post("/api/chat", json={"message": "你要是能查快递就好了"}, headers=headers)
    assert resp.status_code == 200, resp.text
    reply = resp.json()["reply"]
    assert "我已经会了" in reply
    assert "查快递技能" in reply and "相似度" in reply
    assert stubs["built_raws"] == []  # 不重建
    assert hook.pending_intents[uid_row["id"]]["kind"] == "offer_reuse"


def test_upgrade_enters_normal_confirm_flow(client, db_session, stubs):
    headers = _register_and_login(client)
    uid_row = client.get("/api/auth/me", headers=headers).json()
    _setup_llm_config(db_session, uid_row["id"])
    stubs["similar"] = [{"slug": "query_express", "description": "查快递技能", "score": 0.92}]

    resp = client.post("/api/chat", json={"message": "你要是能查快递就好了"}, headers=headers)
    assert "我已经会了" in resp.json()["reply"]

    # 「升级 + 新需求」→ 剥离前缀，回到正常确认流（复述等确认，不直接构建）
    resp = client.post("/api/chat", json={"message": "升级 更强的查快递"}, headers=headers)
    reply = resp.json()["reply"]
    assert "确认一下" in reply and "更强的查快递" in reply
    assert stubs["built_raws"] == []
    entry = hook.pending_intents[uid_row["id"]]
    assert entry["raw"] == "更强的查快递" and entry["kind"] == "confirm"

    # 确认后按新文本构建
    resp = client.post("/api/chat", json={"message": "确认"}, headers=headers)
    assert "提案编号" in resp.json()["reply"]
    assert stubs["built_raws"] == ["更强的查快递"]
    assert uid_row["id"] not in hook.pending_intents


def test_confirm_on_reuse_offer_nudges_instead(client, db_session, stubs):
    headers = _register_and_login(client)
    uid_row = client.get("/api/auth/me", headers=headers).json()
    _setup_llm_config(db_session, uid_row["id"])
    stubs["similar"] = [{"slug": "query_express", "description": "查快递技能", "score": 0.92}]

    resp = client.post("/api/chat", json={"message": "你要是能查快递就好了"}, headers=headers)
    assert "我已经会了" in resp.json()["reply"]

    # 对已有技能说「确认」不合理：引导走「升级」或「取消」，不触发构建
    resp = client.post("/api/chat", json={"message": "确认"}, headers=headers)
    reply = resp.json()["reply"]
    assert "升级" in reply and "取消" in reply
    assert stubs["built_raws"] == []
    assert uid_row["id"] in hook.pending_intents  # 状态保持，仍可升级/取消


def test_low_score_keeps_normal_confirm_flow(client, db_session, stubs):
    headers = _register_and_login(client)
    uid_row = client.get("/api/auth/me", headers=headers).json()
    _setup_llm_config(db_session, uid_row["id"])
    stubs["similar"] = [{"slug": "query_express", "description": "查快递技能", "score": 0.5}]

    resp = client.post("/api/chat", json={"message": "你要是能查快递就好了"}, headers=headers)
    reply = resp.json()["reply"]
    assert "我已经会了" not in reply
    assert "确认一下" in reply  # 低分 → 走原确认流
    assert stubs["built_raws"] == []
    assert hook.pending_intents[uid_row["id"]]["kind"] == "confirm"

    resp = client.post("/api/chat", json={"message": "确认"}, headers=headers)
    assert "提案编号" in resp.json()["reply"]
    assert stubs["built_raws"] == ["你要是能查快递就好了"]
