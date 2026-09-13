# Task B 后端加固测试 — 费用门禁 / 重复请求去重 / 分支存在性校验 / 同用户并发锁
#
# 复用 tests/test_learn.py 的桩件与 fixture（同目录模块，直接 import；
# pytest 会把 import 进来的 fixture 注册到本模块，autouse 的
# _force_subprocess_sandbox 也随之对本模块生效）。
import subprocess

from app.config import settings
from app.learn import service
from app.models import UserSetting

from tests.test_learn import (
    _fake_builder,
    _force_subprocess_sandbox,  # noqa: F401 — autouse，import 即对本模块生效
    _global_llm_key_fallback,  # noqa: F401 — 同上：全局兜底 key 的模块内补偿
    _register_and_login,
    git_repo,  # noqa: F401
)

# 全局 key 的会话级补偿已改为 test_learn.py 内的 autouse fixture（import 即继承）：
# 原先的模块级赋值在 pytest 收集阶段生效，曾污染其他测试文件（settings 泄漏事故）。


def _setup_llm_config(db_session, user_id: int) -> None:
    """给用户写入自己的 LLM 配置（acquire 的费用门禁要求）。"""
    session = db_session()
    try:
        for key in ("llm.provider", "llm.model", "llm.api_key"):
            session.add(UserSetting(user_id=user_id, key=key, value="test"))
        session.commit()
    finally:
        session.close()


def _current_user_id(client, headers) -> int:
    return client.get("/api/auth/me", headers=headers).json()["id"]


# ─── 1. 费用漏洞：未配置 LLM 的用户不许触发构建 ─────────────────────

def test_acquire_without_llm_config_rejected(client, db_session, git_repo, monkeypatch):
    # 即使环境带了全局兜底 key 也视为未配置：构建绝不许花开发者的钱
    monkeypatch.setattr(settings, "llm_api_key", "")
    headers = _register_and_login(client)

    resp = client.post("/api/learn/acquire", json={"request": "我要一个回显工具"}, headers=headers)
    assert resp.status_code == 400, resp.text
    assert "未配置 LLM" in resp.json()["detail"]

    # 没有产生任何提案与分支
    rows = client.get("/api/learn/proposals", headers=headers).json()
    assert rows == []
    branches = subprocess.run(["git", "branch", "--list"], cwd=git_repo,
                              capture_output=True, text=True).stdout
    assert "skill/" not in branches


# ─── 2. 重复请求去重：同一需求复用旧提案，不重建不建分支 ─────────────

def test_acquire_duplicate_returns_same_proposal(client, db_session, git_repo, monkeypatch):
    monkeypatch.setattr("app.learn.builder.build_tool", _fake_builder())
    headers = _register_and_login(client)
    _setup_llm_config(db_session, _current_user_id(client, headers))

    r1 = client.post("/api/learn/acquire", json={"request": "我要一个回显工具"}, headers=headers)
    assert r1.status_code == 200, r1.text
    p1 = r1.json()
    assert p1["duplicate"] is False and p1["status"] == "pending"

    tip_before = subprocess.run(["git", "rev-parse", "skill/demo_echo"],
                                cwd=git_repo, capture_output=True, text=True).stdout.strip()

    # 完全相同的文本（首尾带空白也算相同）→ 返回旧提案
    r2 = client.post("/api/learn/acquire", json={"request": "  我要一个回显工具  "}, headers=headers)
    assert r2.status_code == 200, r2.text
    p2 = r2.json()
    assert p2["duplicate"] is True
    assert p2["id"] == p1["id"]

    tip_after = subprocess.run(["git", "rev-parse", "skill/demo_echo"],
                               cwd=git_repo, capture_output=True, text=True).stdout.strip()
    assert tip_after == tip_before  # 没有重建、没有新提交

    rows = client.get("/api/learn/proposals", headers=headers).json()
    assert len(rows) == 1  # 没有新建提案

    # 不同文本 → 正常走新建（去重不能误伤新需求）
    r3 = client.post("/api/learn/acquire", json={"request": "我要一个翻译工具"}, headers=headers)
    assert r3.status_code == 200, r3.text
    p3 = r3.json()
    assert p3["duplicate"] is False and p3["id"] != p1["id"]


# ─── 3. 批准前分支存在性校验：分支没了 → 400 且提案转 failed ─────────

def test_approve_fails_when_branch_deleted(client, db_session, git_repo, monkeypatch):
    monkeypatch.setattr("app.learn.builder.build_tool", _fake_builder())
    headers = _register_and_login(client)
    _setup_llm_config(db_session, _current_user_id(client, headers))

    proposal = client.post("/api/learn/acquire", json={"request": "我要一个回显工具"},
                           headers=headers).json()
    assert proposal["status"] == "pending"

    # 手动删掉候选分支（连同 worktree 挂载一起清）
    service.discard_branch(proposal["branch"])
    out = subprocess.run(["git", "branch", "--list", "skill/demo_echo"],
                         cwd=git_repo, capture_output=True, text=True).stdout
    assert "skill/demo_echo" not in out

    resp = client.post(f"/api/learn/proposals/{proposal['id']}/approve",
                       json={"keys": {}}, headers=headers)
    assert resp.status_code == 400, resp.text
    assert "分支已不存在" in resp.json()["detail"]

    rows = client.get("/api/learn/proposals", headers=headers).json()
    assert rows[0]["status"] == "failed"


# ─── 4. 同用户并发锁：上一条没学完不许并发再开一条 ──────────────────

def test_concurrent_build_locked_per_user(client, db_session, git_repo, monkeypatch):
    monkeypatch.setattr("app.learn.builder.build_tool", _fake_builder())
    headers = _register_and_login(client)
    uid = _current_user_id(client, headers)
    _setup_llm_config(db_session, uid)

    service._BUILDING.add(uid)  # 模拟该用户已有一条构建在跑
    try:
        resp = client.post("/api/learn/acquire", json={"request": "再来个别的工具"}, headers=headers)
        assert resp.status_code == 429, resp.text
        assert "学习中" in resp.json()["detail"]
    finally:
        service._BUILDING.discard(uid)

    # 锁释放后同一用户可正常构建
    ok = client.post("/api/learn/acquire", json={"request": "再来个别的工具"}, headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "pending"


def test_build_lock_released_after_failed_build(client, db_session, git_repo, monkeypatch):
    async def boom(user_request, cfg, repair_feedback=None):
        raise RuntimeError("LLM 炸了")

    monkeypatch.setattr("app.learn.builder.build_tool", boom)
    headers = _register_and_login(client)
    _setup_llm_config(db_session, _current_user_id(client, headers))

    r1 = client.post("/api/learn/acquire", json={"request": "我要一个回显工具"}, headers=headers)
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "failed"

    # 失败后锁必须已被 finally 释放：换正常 builder 再来一次应能成功
    monkeypatch.setattr("app.learn.builder.build_tool", _fake_builder())
    r2 = client.post("/api/learn/acquire", json={"request": "我要一个回显工具"}, headers=headers)
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "pending" and body["duplicate"] is False  # failed 提案不算重复
