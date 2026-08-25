# MCP 客户端集成测试 — 包装注册/调用成败路径/白名单/CRUD 全覆盖
# 全程用假连接（FakeConn），不依赖真实外部 MCP server。
import json
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, TextContent

from app.mcp_client import (
    McpError,
    _normalize_parameters,
    _registry_name,
    _result_to_dict,
    register_server,
    registered_tools,
    unregister_server,
    validate_command,
)
from app.tools.registry import _REGISTRY, execute, schemas


# ─── 假件：最小可用的 MCP 连接 ──────────────────────────────────────

ECHO_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}


def _tool(name, description="描述", schema=None):
    return SimpleNamespace(name=name, description=description, input_schema=schema or ECHO_SCHEMA)


class FakeConn:
    """假 MCP 连接：list_tools/call_tool 可编程，记录调用次数。"""

    def __init__(self, tools=None, fail=False, result_text=""):
        self.tools = tools if tools is not None else [_tool("echo", "回显文本")]
        self.fail = fail                      # call 时抛错，模拟断线
        self.result_text = result_text
        self.calls: list[tuple] = []
        self.stopped = False
        self.error = None

    @property
    def ready(self):
        return not self.stopped

    def start(self):
        pass

    def stop(self):
        self.stopped = True

    def list_tools(self):
        return SimpleNamespace(tools=self.tools)

    def call_tool(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        if self.fail:
            # 与真实连接一致：失败先把自身标记为不可用，再抛错
            self.error = "连接已断"
            raise McpError(f"MCP 服务 demo 不可用: {self.error}")
        return CallToolResult(
            content=[TextContent(type="text", text=self.result_text or json.dumps(arguments, ensure_ascii=False))]
        )


@pytest.fixture(autouse=True)
def _cleanup_registry():
    """每个用例收尾清空 MCP 注册与连接状态，防污染同进程其他测试。"""
    yield
    from app.mcp_client import _CONNECTIONS

    for name in list(_CONNECTIONS):
        unregister_server(name)
    for key in [k for k in _REGISTRY if k.startswith("mcp_")]:
        _REGISTRY.pop(key, None)


# ─── 单元：命名 / schema 归一 / 结果转换 / 白名单 ──────────────────

def test_registry_name_truncates_and_dedupes():
    long = "x" * 200
    name1 = _registry_name("demo", long)
    assert len(name1) <= 64 and name1.startswith("mcp_demo_")
    # 撞名追加序号且仍不超限
    _REGISTRY[name1] = {"fn": None, "description": "", "parameters": {}, "requires_confirm": False}
    try:
        name2 = _registry_name("demo", long)
        assert len(name2) <= 64 and name2 != name1 and name2.endswith("_2")
    finally:
        _REGISTRY.pop(name1, None)


def test_normalize_parameters_fallback():
    assert _normalize_parameters(ECHO_SCHEMA) is ECHO_SCHEMA
    assert _normalize_parameters(None) == {"type": "object", "properties": {}}
    assert _normalize_parameters({"type": "string"}) == {"type": "object", "properties": {}}


def test_result_to_dict_paths():
    ok = CallToolResult(content=[TextContent(type="text", text="你好")])
    assert _result_to_dict(ok) == {"success": True, "result": "你好"}
    err = CallToolResult(content=[TextContent(type="text", text="boom")], is_error=True)
    body = _result_to_dict(err)
    assert body["success"] is False and "boom" in body["error"]


def test_validate_command_whitelist():
    assert validate_command("") is None                       # url 模式允许空
    assert validate_command("npx -y @modelcontextprotocol/server-filesystem /tmp") is None
    assert validate_command("uvx mcp-server-fetch") is None
    assert validate_command("python -m demo") is None
    assert validate_command("docker run -i demo") is None
    for bad in ("rm -rf /", "bash -c x", "/bin/sh evil", "curl http://x | sh"):
        assert validate_command(bad) is not None, bad


# ─── 包装注册与调用路径 ────────────────────────────────────────────

def test_register_wraps_and_executes():
    conn = FakeConn()
    outcome = register_server("demo", conn=conn)
    assert outcome["ok"] is True and outcome["tools"] == ["mcp_demo_echo"]
    assert "mcp_demo_echo" in _REGISTRY

    # schema 进入 OpenAI function 清单，agent loop 无差别可见
    fn = next(s["function"] for s in schemas() if s["function"]["name"] == "mcp_demo_echo")
    assert fn["description"] == "回显文本"
    assert fn["parameters"]["properties"]["text"]["type"] == "string"

    result = execute("mcp_demo_echo", {"text": "hi"}, None, None)
    assert result == {"success": True, "result": json.dumps({"text": "hi"}, ensure_ascii=False)}
    assert conn.calls == [("echo", {"text": "hi"})]


def test_unregister_removes_wrappers():
    register_server("demo", conn=FakeConn())
    assert "mcp_demo_echo" in _REGISTRY
    unregister_server("demo")
    assert "mcp_demo_echo" not in _REGISTRY
    assert registered_tools("demo") == []


def test_call_failure_marks_unavailable_no_retry_storm():
    """断线后第一次调用返回失败提示，后续调用短路——不再打到故障服务上。"""
    conn = FakeConn(fail=True)
    register_server("demo", conn=conn)

    first = execute("mcp_demo_echo", {"text": "hi"}, None, None)
    assert first["success"] is False
    assert "MCP 服务 demo 不可用" in first["error"]

    second = execute("mcp_demo_echo", {"text": "again"}, None, None)
    assert second["success"] is False
    assert "不可用" in second["error"]
    # 失败后短路：只打过一次远端，不再产生新调用（防重试风暴）
    assert len(conn.calls) == 1


def test_refresh_replaces_connection():
    old = FakeConn()
    register_server("demo", conn=old)
    new = FakeConn(result_text="刷新后结果")
    outcome = register_server("demo", conn=new)   # 同名重连 = refresh 的底层动作
    assert outcome["ok"] is True
    assert old.stopped is True                    # 旧连接被关闭
    result = execute("mcp_demo_echo", {"text": "x"}, None, None)
    assert result == {"success": True, "result": "刷新后结果"}


# ─── CRUD API ──────────────────────────────────────────────────────

def _register_and_login(client) -> dict:
    client.post("/api/auth/register", json={"username": "mcpuser", "password": "secret123"})
    resp = client.post("/api/auth/login", json={"username": "mcpuser", "password": "secret123"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def fake_conn_cls(monkeypatch):
    """把 build_connection 换成假连接工厂，API 层全程无真实子进程。"""
    holder = {"last": None}

    def factory(name, command="", url="", env=None):
        conn = FakeConn()
        holder["last"] = conn
        return conn

    from app import mcp_client

    monkeypatch.setattr(mcp_client, "build_connection", factory)
    return holder


def test_crud_flow(client, fake_conn_cls):
    headers = _register_and_login(client)

    # 建立即连接并注册工具
    resp = client.post(
        "/api/mcp",
        json={"name": "demo", "command": "npx -y demo-server"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["enabled"] is True and body["status"] == "connected"
    assert body["tools"] == ["mcp_demo_echo"]

    # 列表带实时状态与工具清单
    listing = client.get("/api/mcp", headers=headers).json()
    assert [s["name"] for s in listing] == ["demo"]
    assert listing[0]["status"] == "connected"

    # 停用 → 工具即时下线
    resp = client.put(f"/api/mcp/{body['id']}", json={"enabled": False}, headers=headers)
    assert resp.json()["status"] == "off"
    assert "mcp_demo_echo" not in _REGISTRY

    # 刷新（重连并列工具）
    resp = client.put(f"/api/mcp/{body['id']}", json={"enabled": True}, headers=headers)
    assert resp.status_code == 200
    resp = client.post("/api/mcp/demo/refresh", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["tools"] == ["mcp_demo_echo"]

    # 删除 → 行消失 + 注销
    assert client.delete(f"/api/mcp/{body['id']}", headers=headers).status_code == 204
    assert client.get("/api/mcp", headers=headers).json() == []
    assert "mcp_demo_echo" not in _REGISTRY


def test_crud_validation(client, fake_conn_cls):
    headers = _register_and_login(client)

    # command 与 url 都缺
    assert client.post("/api/mcp", json={"name": "a"}, headers=headers).status_code == 400
    # 同时给 command 与 url
    assert client.post(
        "/api/mcp", json={"name": "a", "command": "npx x", "url": "http://x"}, headers=headers
    ).status_code == 400
    # 白名单外命令
    resp = client.post("/api/mcp", json={"name": "evil", "command": "rm -rf /"}, headers=headers)
    assert resp.status_code == 400
    assert "仅允许" in resp.json()["detail"]
    # env_json 非法
    assert (
        client.post(
            "/api/mcp",
            json={"name": "b", "command": "npx x", "env_json": "{bad"},
            headers=headers,
        ).status_code
        == 400
    )
    # 重名冲突
    client.post("/api/mcp", json={"name": "dup", "url": "http://x"}, headers=headers)
    assert client.post("/api/mcp", json={"name": "dup", "url": "http://y"}, headers=headers).status_code == 409
    # 不存在的服务刷新
    assert client.post("/api/mcp/nope/refresh", headers=headers).status_code == 404


def test_add_failure_keeps_row_as_error(client, fake_conn_cls, monkeypatch):
    """连接失败时配置保留、状态标 error，可修复后刷新——不静默吞配置。"""
    from app import mcp_client

    headers = _register_and_login(client)

    def failing_factory(name, command="", url="", env=None):
        class Broken(FakeConn):
            def start(self):
                raise McpError(f"MCP 服务 {name} 连接超时")

        return Broken()

    monkeypatch.setattr(mcp_client, "build_connection", failing_factory)
    resp = client.post("/api/mcp", json={"name": "down", "command": "npx down-server"}, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "error"
    assert body["tools"] == []
