# 年度体检 + 技能市场 测试
# 覆盖：体检金题生成 / 重放打分（mock 工具执行）/ 市场浏览与安装走沙箱 / 未授权 401。
import json
import subprocess
from datetime import datetime, timezone

import pytest

from app.learn import checkup, service


# ─── 桩件：一个合规的最小技能（市场里已上线的来源） ──────────────────────

MARKET_TOOL = '''
from app.tools.registry import tool


@tool(
    name="market_echo",
    description="市场回显（测试技能）",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string", "description": "原文"}},
        "required": ["text"],
    },
)
def market_echo(args: dict, user, db) -> dict:
    text = str(args.get("text", ""))
    return {"success": True, "echo": text}
'''

MARKET_TESTS = '''
def test_echo(candidate):
    assert candidate.market_echo({"text": "hi"}, None, None) == {"success": True, "echo": "hi"}
'''


@pytest.fixture()
def git_repo(tmp_path, monkeypatch):
    """带最小结构的临时 git 仓库，并把 service 指过去（复用 test_learn 的套路）。"""
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
    subprocess.run(["git", "worktree", "prune"], cwd=repo, capture_output=True)


def _register_and_login(client, username: str) -> dict:
    client.post("/api/auth/register", json={"username": username, "password": "secret123"})
    resp = client.post("/api/auth/login", json={"username": username, "password": "secret123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _add_user(db_session, username: str) -> "object":
    """直接落库一个用户，返回带 id 的轻量对象。"""
    from app.models import User

    session = db_session()
    u = User(username=username, password_hash="x")
    session.add(u)
    session.commit()
    session.refresh(u)
    uid = u.id
    session.close()
    return type("U", (), {"id": uid, "username": username})()


def _add_tool_call(db_session, user_id: int, tool: str, args: dict, success: int = 1) -> None:
    """给用户建一条会话并记录一次工具调用。"""
    from app.models import Conversation, ToolCallLog

    session = db_session()
    conv = Conversation(user_id=user_id, title="体检样本")
    session.add(conv)
    session.commit()
    session.refresh(conv)
    session.add(ToolCallLog(
        conversation_id=conv.id, tool_name=tool,
        arguments=json.dumps(args, ensure_ascii=False),
        result=json.dumps({"success": bool(success), "tool": tool}, ensure_ascii=False),
        success=success,
        created_at=datetime.now(timezone.utc),
    ))
    session.commit()
    session.close()


# ─── 体检：金题生成 ──────────────────────────────────────────────────

def test_checkup_generates_golden(db_session):
    from app.models import UserSetting

    user = _add_user(db_session, "checkup_gen")
    # 25 次成功 + 5 次失败，只应抽到最近 20 次成功
    for i in range(25):
        _add_tool_call(db_session, user.id, "calculator", {"expr": str(i)}, success=1)
    for i in range(5):
        _add_tool_call(db_session, user.id, "calculator", {"expr": "boom"}, success=0)

    session = db_session()
    try:
        result = checkup.run_checkup(session, user.id)
        assert result["count"] == 20
        assert len(result["golden"]) == 20
        # 全是成功调用；时间正序（老的在前）
        tools = [g["tool"] for g in result["golden"]]
        assert all(g["tool"] == "calculator" for g in result["golden"])
        args = [g["arguments"] for g in result["golden"]]
        assert args[0] == {"expr": "5"}  # 最早的 5 条失败被挤出
        assert args[-1] == {"expr": "24"}
        assert "result_summary" in result["golden"][0]

        row = session.query(UserSetting).filter_by(user_id=user.id, key=checkup.GOLDEN_KEY).first()
        assert row is not None
        assert len(json.loads(row.value)) == 20

        # 覆盖旧：再抽一次（此时只有 20 次成功），count 仍对得上
        again = checkup.run_checkup(session, user.id)
        assert again["count"] == 20
    finally:
        session.close()


# ─── 体检：重放打分（mock 工具执行） ─────────────────────────────────

def test_checkup_replay_and_score_with_mock(db_session, monkeypatch):
    import importlib

    user = _add_user(db_session, "checkup_replay")
    # 两条 calculator + 一条 get_weather
    _add_tool_call(db_session, user.id, "calculator", {"expr": "1+1"})
    _add_tool_call(db_session, user.id, "calculator", {"expr": "2*3"})
    _add_tool_call(db_session, user.id, "get_weather", {"city": "上海"})

    def fake_execute(name, args, user, db, cfg=None):
        if name == "calculator":
            return {"success": True, "result": 4}
        return {"success": False, "error": "mock: 天气服务不可用"}

    # app.tools.registry 在包命名空间被 __init__ 里的 registry 字典遮蔽，
    # 用 importlib 取真正的模块再打桩。
    reg_module = importlib.import_module("app.tools.registry")
    monkeypatch.setattr(reg_module, "execute", fake_execute)

    session = db_session()
    try:
        golden = checkup.run_checkup(session, user.id)["golden"]
        assert len(golden) == 3
        results = checkup.replay_golden(session, user, golden)
        stats = checkup.score(results)
        assert stats == {"total": 3, "ok": 2, "rate": 67}
    finally:
        session.close()


def test_weekly_checkup_notifies_warn_below_threshold(db_session, monkeypatch):
    import importlib

    from app.models import Notification

    user = _add_user(db_session, "checkup_warn")
    _add_tool_call(db_session, user.id, "calculator", {"expr": "1+1"})
    _add_tool_call(db_session, user.id, "calculator", {"expr": "2*3"})
    _add_tool_call(db_session, user.id, "get_weather", {"city": "上海"})

    def fake_execute(name, args, user, db, cfg=None):
        if name == "calculator":
            return {"success": True, "result": 4}
        return {"success": False, "error": "mock 失败"}

    reg_module = importlib.import_module("app.tools.registry")
    monkeypatch.setattr(reg_module, "execute", fake_execute)

    session = db_session()
    try:
        summaries = checkup.run_weekly_checkups(session)
        assert summaries == ["user%d: 3 项 67%% 正常" % user.id]

        note = session.query(Notification).filter(Notification.user_id == user.id).first()
        assert note is not None
        assert note.title == "⚠️ 贾维斯体检：3 项能力 67% 正常"
        assert "get_weather" in note.content  # 异常项列在正文

        # 周节流：刚跑过，再跑不再产生通知
        before = session.query(Notification).count()
        checkup.run_weekly_checkups(session)
        assert session.query(Notification).count() == before
    finally:
        session.close()


def test_weekly_checkup_notifies_ok_at_high_rate(db_session, monkeypatch):
    import importlib

    from app.models import Notification

    user = _add_user(db_session, "checkup_ok")
    _add_tool_call(db_session, user.id, "calculator", {"expr": "1+1"})
    _add_tool_call(db_session, user.id, "calculator", {"expr": "2*3"})

    def fake_execute(name, args, user, db, cfg=None):
        return {"success": True, "result": 4}

    reg_module = importlib.import_module("app.tools.registry")
    monkeypatch.setattr(reg_module, "execute", fake_execute)

    session = db_session()
    try:
        checkup.run_weekly_checkups(session)
        note = session.query(Notification).filter(Notification.user_id == user.id).first()
        assert note is not None
        assert note.title == "贾维斯体检：2 项能力 100% 正常"  # 达标不加 ⚠️
        assert "⚠️" not in note.title
    finally:
        session.close()


# ─── 市场：浏览 / 导出 ──────────────────────────────────────────────

def _seed_approved_skill(db_session, author_id: int, slug: str = "market_echo") -> int:
    from app.models import SkillProposal

    session = db_session()
    p = SkillProposal(
        user_id=author_id, slug=slug, title="回显", description="把话原样复述给你听",
        status="approved", tool_code=MARKET_TOOL, test_code=MARKET_TESTS,
        test_output="门禁/沙箱通过", required_keys="{}", branch="",
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    pid = p.id
    session.close()
    return pid


def test_market_list_shows_approved_skills_with_author(client, db_session):
    author = _add_user(db_session, "market_author")
    _seed_approved_skill(db_session, author.id)
    headers = _register_and_login(client, "market_browser")

    resp = client.get("/api/market/skills", headers=headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["slug"] == "market_echo"
    assert rows[0]["description"] == "把话原样复述给你听"
    assert rows[0]["author"] == "market_author"


def test_market_export_package(client, db_session):
    author = _add_user(db_session, "export_author")
    pid = _seed_approved_skill(db_session, author.id)
    headers = _register_and_login(client, "export_browser")

    resp = client.get(f"/api/market/skills/{pid}/export", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["slug"] == "market_echo"
    assert body["code"] == MARKET_TOOL
    assert body["tests"] == MARKET_TESTS
    assert body["description"] == "把话原样复述给你听"


def test_market_export_rejects_non_approved(client, db_session):
    from app.models import SkillProposal

    author = _add_user(db_session, "export_author2")
    session = db_session()
    p = SkillProposal(
        user_id=author.id, slug="wip", title="未上线", description="草稿",
        status="pending", tool_code="", test_code="", required_keys="{}", branch="",
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    pid = p.id
    session.close()

    headers = _register_and_login(client, "export_browser2")
    resp = client.get(f"/api/market/skills/{pid}/export", headers=headers)
    assert resp.status_code == 404


# ─── 市场：安装走门禁+沙箱，复用 service 逻辑上线 ─────────────────────

def test_market_install_runs_sandbox_and_goes_live(client, db_session, git_repo, monkeypatch):
    from app.models import SkillProposal
    from app.tools.registry import _REGISTRY

    author = _add_user(db_session, "install_author")
    pid = _seed_approved_skill(db_session, author.id)
    headers = _register_and_login(client, "install_buyer")

    # 沙箱被真实调用（spy），直接放行
    calls = []

    def fake_run_tests(tool_code, test_code, slug="cand"):
        calls.append(slug)
        return True, "pytest: 1 passed"

    monkeypatch.setattr("app.learn.sandbox.run_tests", fake_run_tests)

    resp = client.post(f"/api/market/skills/{pid}/install", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["slug"] == "market_echo"
    assert body["status"] == "approved"
    assert body["message"] == "技能已上线"
    assert calls == ["market_echo"]  # 安装确实走了沙箱重验

    # 本用户多了一条提案，代码来自来源技能
    session = db_session()
    try:
        buyer_id = client.get("/api/auth/me", headers=headers).json()["id"]
        mine = (
            session.query(SkillProposal)
            .filter(SkillProposal.user_id == buyer_id, SkillProposal.slug == "market_echo")
            .all()
        )
        assert len(mine) == 1
        assert mine[0].tool_code == MARKET_TOOL
        assert mine[0].status == "approved"
        # 目标技能文件落进主工作区
        assert (git_repo / "app/tools/skills/market_echo.py").exists()
    finally:
        session.close()

    # 热激活：工具可直接执行
    from app.tools.registry import execute

    assert execute("market_echo", {"text": "hi"}, None, None) == {"success": True, "echo": "hi"}
    _REGISTRY.pop("market_echo", None)


def test_market_install_rejects_when_sandbox_fails(client, db_session, monkeypatch):
    author = _add_user(db_session, "install_author2")
    pid = _seed_approved_skill(db_session, author.id)
    headers = _register_and_login(client, "install_buyer2")

    monkeypatch.setattr(
        "app.learn.sandbox.run_tests", lambda tc, tt, slug="cand": (False, "断言失败")
    )

    resp = client.post(f"/api/market/skills/{pid}/install", headers=headers)
    assert resp.status_code == 422, resp.text
    assert "沙箱重验未通过" in resp.json()["detail"]


# ─── 未授权访问 401 ─────────────────────────────────────────────────

def test_market_requires_auth(client):
    assert client.get("/api/market/skills").status_code == 401
    assert client.get("/api/market/skills/1/export").status_code == 401
    assert client.post("/api/market/skills/1/install").status_code == 401
