# 自学习管线测试 — 门禁/沙箱/服务编排全链路（构建器用桩替换，不依赖真实 LLM）
import json
import subprocess
from pathlib import Path

import pytest

from app.learn import gate, service


# ─── 桩件：一个合规的最小工具 + 测试 ────────────────────────────────

GOOD_TOOL = '''
from app.tools.registry import tool


@tool(
    name="demo_echo",
    description="回显文本（测试技能）",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string", "description": "原文"}},
        "required": ["text"],
    },
)
def demo_echo(args: dict, user, db) -> dict:
    text = str(args.get("text", ""))
    if not text:
        return {"success": False, "error": "text 不能为空"}
    return {"success": True, "echo": text}
'''

GOOD_TESTS = '''
def test_echo(candidate):
    assert candidate.demo_echo({"text": "hi"}, None, None) == {"success": True, "echo": "hi"}


def test_echo_empty(candidate):
    assert candidate.demo_echo({"text": ""}, None, None)["success"] is False
'''


@pytest.fixture(autouse=True)
def _force_subprocess_sandbox(monkeypatch):
    """测试不依赖 Docker 状态：统一走子进程沙箱。"""
    monkeypatch.setenv("LEARN_SANDBOX", "subprocess")


def _fake_builder(tool=GOOD_TOOL, tests=GOOD_TESTS):
    async def fake_build_tool(user_request, cfg, repair_feedback=None):
        return tool, tests

    return fake_build_tool


@pytest.fixture()
def git_repo(tmp_path, monkeypatch):
    """带最小结构的临时 git 仓库，并把 service 指过去。"""
    repo = tmp_path / "repo"
    (repo / "app/tools/skills").mkdir(parents=True)
    (repo / "tests/skills").mkdir(parents=True)
    (repo / "README.md").write_text("demo", encoding="utf-8")
    (repo / "app/tools/skills/__init__.py").write_text("", encoding="utf-8")
    def g(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    g("init", "-q")
    g("config", "user.email", "t@t.local")
    g("config", "user.name", "t")
    g("add", "-A")
    g("commit", "-qm", "init")
    monkeypatch.setattr(service, "PROJECT_ROOT", repo)
    yield repo
    # 清理挂载到本仓库的 worktree
    subprocess.run(["git", "worktree", "prune"], cwd=repo, capture_output=True)


def _register_and_login(client) -> dict:
    client.post("/api/auth/register", json={"username": "learner1", "password": "secret123"})
    resp = client.post("/api/auth/login", json={"username": "learner1", "password": "secret123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ─── 门禁 ──────────────────────────────────────────────────────────

def test_gate_blocks_dangerous_code():
    errors, _ = gate.static_gate(
        "import os\nfrom app.tools.registry import tool\n@tool(name='x', description='d', parameters={})\ndef x(args, user, db):\n    return os.system('rm -rf /')\n",
        "def test_x():\n    assert True\n",
    )
    assert any("os.system" in e for e in errors)


def test_gate_requires_single_tool():
    errors, _ = gate.static_gate("x = 1\n", "assert True\n")
    assert any("@tool" in e for e in errors)


def test_extract_required_keys():
    code = 'REQUIRED_KEYS = {"WEATHER_API_KEY": "天气服务密钥"}\nimport os\nv = os.getenv("OTHER_THING")\n'
    keys = gate.extract_required_keys(code)
    assert keys["WEATHER_API_KEY"] == "天气服务密钥"
    assert "OTHER_THING" in keys


def test_slug_check():
    assert gate.check_slug("demo_echo") is None
    assert gate.check_slug("1bad") is not None
    assert gate.check_slug("") is not None


# ─── 沙箱 ──────────────────────────────────────────────────────────

def test_sandbox_passes_good_tool():
    from app.learn.sandbox import run_tests

    passed, output = run_tests(GOOD_TOOL, GOOD_TESTS, "demo_echo")
    assert passed, output


def test_sandbox_fails_bad_test():
    from app.learn.sandbox import run_tests

    passed, output = run_tests(GOOD_TOOL, "def test_wrong(candidate):\n    assert False\n", "demo_echo")
    assert not passed


# ─── 服务编排（API 级端到端）───────────────────────────────────────

def test_acquire_approve_flow(client, db_session, git_repo, monkeypatch):
    monkeypatch.setattr("app.learn.builder.build_tool", _fake_builder())
    headers = _register_and_login(client)

    resp = client.post("/api/learn/acquire", json={"request": "我要一个回显工具"}, headers=headers)
    assert resp.status_code == 200, resp.text
    proposal = resp.json()
    assert proposal["status"] == "pending"
    assert proposal["slug"] == "demo_echo"
    assert proposal["branch"] == "skill/demo_echo"

    # 分支真实存在且含候选文件；主分支还没有该文件
    branches = subprocess.run(["git", "branch", "--list", "skill/demo_echo"],
                              cwd=git_repo, capture_output=True, text=True).stdout
    assert "skill/demo_echo" in branches
    assert not (git_repo / "app/tools/skills/demo_echo.py").exists()

    # 批准 → 合并进当前分支 + 热注册
    resp = client.post(f"/api/learn/proposals/{proposal['id']}/approve", json={"keys": {}}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True and body["live"] is True

    # 主工作区出现文件；工具已注册且可执行
    assert (git_repo / "app/tools/skills/demo_echo.py").exists()
    from app.tools.registry import _REGISTRY, execute

    assert "demo_echo" in _REGISTRY
    assert execute("demo_echo", {"text": "hello"}, None, None) == {"success": True, "echo": "hello"}

    # 收尾：清掉进程内注册，防污染其他用例
    _REGISTRY.pop("demo_echo", None)

    # 提案状态落库
    rows = client.get("/api/learn/proposals", headers=headers).json()
    assert rows[0]["status"] == "approved"


def test_acquire_reject_flow(client, db_session, git_repo, monkeypatch):
    monkeypatch.setattr("app.learn.builder.build_tool", _fake_builder())
    headers = _register_and_login(client)

    proposal = client.post("/api/learn/acquire", json={"request": "再来个回显"}, headers=headers).json()
    resp = client.post(f"/api/learn/proposals/{proposal['id']}/reject", json={}, headers=headers)
    assert resp.json()["ok"] is True

    branches = subprocess.run(["git", "branch", "--list", "skill/demo_echo"],
                              cwd=git_repo, capture_output=True, text=True).stdout
    assert "skill/demo_echo" not in branches  # 拒绝后零残留
    assert not (git_repo / "app/tools/skills/demo_echo.py").exists()


def test_missing_key_blocks_approval(client, db_session, git_repo, monkeypatch):
    keyed_tool = GOOD_TOOL.replace(
        "from app.tools.registry import tool",
        'from app.tools.registry import tool\n\nREQUIRED_KEYS = {"DEMO_API_KEY": "演示用密钥"}',
    )
    monkeypatch.setattr("app.learn.builder.build_tool", _fake_builder(tool=keyed_tool))
    headers = _register_and_login(client)

    proposal = client.post("/api/learn/acquire", json={"request": "要 key 的回显"}, headers=headers).json()
    required = json.loads(proposal["required_keys"]) if isinstance(proposal["required_keys"], str) else proposal["required_keys"]
    assert "DEMO_API_KEY" in required

    resp = client.post(f"/api/learn/proposals/{proposal['id']}/approve", json={"keys": {}}, headers=headers)
    body = resp.json()
    assert body.get("ok") is False and "DEMO_API_KEY" in body.get("missing_keys", {})

    # 补上 key 再批准 → 成功上线，key 落库
    resp = client.post(
        f"/api/learn/proposals/{proposal['id']}/approve",
        json={"keys": {"DEMO_API_KEY": "sk-demo"}},
        headers=headers,
    )
    assert resp.json()["ok"] is True
    from app.models import LearnKey

    session = db_session()
    try:
        row = session.query(LearnKey).filter_by(key_name="DEMO_API_KEY").first()
        assert row is not None and row.value == "sk-demo"
    finally:
        session.close()

    # 收尾：清掉进程内注册，防污染其他用例
    from app.tools.registry import _REGISTRY

    _REGISTRY.pop("demo_echo", None)


# ─── 聊天钩子（对话里完成学习闭环）─────────────────────────────────

def _setup_llm_config(db_session, user_id: int) -> None:
    from app.models import UserSetting

    session = db_session()
    try:
        for key in ("llm.provider", "llm.model", "llm.api_key"):
            session.add(UserSetting(user_id=user_id, key=key, value="test"))
        session.commit()
    finally:
        session.close()


def test_chat_learn_loop(client, db_session, git_repo, monkeypatch):
    import re as _re

    monkeypatch.setattr("app.learn.builder.build_tool", _fake_builder())
    headers = _register_and_login(client)
    uid_row = client.get("/api/auth/me", headers=headers).json()
    _setup_llm_config(db_session, uid_row["id"])

    # ① 对话触发学习 → 确认流：先回确认话术，用户「确认」后才构建
    resp = client.post("/api/chat", json={"message": "你要是能有个回显工具就好了"}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert "确认一下" in resp.json()["reply"]
    resp = client.post("/api/chat", json={"message": "确认"}, headers=headers)
    assert resp.status_code == 200, resp.text
    reply = resp.json()["reply"]
    assert "提案编号" in reply
    match = _re.search(r"\[LEARN_PROPOSAL\](\{.*?\})\[\/LEARN_PROPOSAL\]", reply)
    assert match, reply
    proposal_id = json.loads(match.group(1))["id"]

    # ② 对话批准 → 上线且可执行
    resp = client.post("/api/chat", json={"message": f"批准 {proposal_id}"}, headers=headers)
    assert "学会了" in resp.json()["reply"]
    from app.tools.registry import _REGISTRY, execute

    assert execute("demo_echo", {"text": "ok"}, None, None)["success"] is True
    _REGISTRY.pop("demo_echo", None)


def test_chat_learn_reject_loop(client, db_session, git_repo, monkeypatch):
    import re as _re

    monkeypatch.setattr("app.learn.builder.build_tool", _fake_builder())
    headers = _register_and_login(client)
    uid_row = client.get("/api/auth/me", headers=headers).json()
    _setup_llm_config(db_session, uid_row["id"])

    resp = client.post("/api/chat", json={"message": "教你会回显吧"}, headers=headers)
    assert "确认一下" in resp.json()["reply"]
    resp = client.post("/api/chat", json={"message": "确认"}, headers=headers)
    match = _re.search(r"\[LEARN_PROPOSAL\](\{.*?\})\[\/LEARN_PROPOSAL\]", resp.json()["reply"])
    proposal_id = json.loads(match.group(1))["id"]

    resp = client.post("/api/chat", json={"message": f"拒绝 {proposal_id}"}, headers=headers)
    assert "放弃" in resp.json()["reply"]
    branches = subprocess.run(
        ["git", "branch", "--list", "skill/demo_echo"], cwd=git_repo, capture_output=True, text=True
    ).stdout
    assert "skill/demo_echo" not in branches
