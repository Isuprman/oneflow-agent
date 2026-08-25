# MCP 客户端集成 —— 连接管理器 + 动态工具注册
#
# 设计（动态工具包装并入本文件，二选一取「并入」）：
#   包装函数与连接生命周期强耦合（断线标记、重连后整体换新），拆两个文件只会
#   多出一份共享可变状态，故连接管理与注册逻辑收在同一处。
#
# 连接模型：MCP 会话必须常驻 async 上下文，而 registry.execute 是同步入口、且
# 可能运行在 FastAPI 事件循环线程上。因此每个 server 独占一条后台线程 + 事件循环，
# 传输层与 ClientSession 在其中保持打开；同步调用经 run_coroutine_threadsafe
# 投递到该循环 —— 绝不在调用方线程另起事件循环。
#
# 信任/用量体系自动覆盖：工具直接写进 app/tools/registry._REGISTRY，engine 的
# 信任旋钮（ask_all 全确认）与 ToolCallLog 用量流水对 MCP 工具天然生效，无需特判。
#
# 安全：command 仅允许白名单前缀启动器（npx/uvx/python/python3/docker）——
# 这些启动器自身负责解析包名/脚本参数，杜绝把任意 shell 命令串进子进程执行。
import asyncio
import concurrent.futures
import json
import logging
import shlex
import threading

from .tools.registry import _REGISTRY

logger = logging.getLogger(__name__)

# 启动命令白名单：仅允许这些解释器/运行器作为 stdio 子进程入口，防任意命令执行
ALLOWED_COMMANDS = ("npx", "uvx", "python", "python3", "docker")

# 工具注册名上限：与 tool_calls_log.tool_name / pending_actions.tool_name 列宽一致
MAX_TOOL_NAME_LEN = 64

_CALL_TIMEOUT = 30  # 单次工具调用超时（秒）

# 进程级单例状态：server 名 -> {"conn": McpConnection, "tools": [已注册工具名]}
_CONNECTIONS: dict[str, dict] = {}
# 最近一次连接失败原因（无存活连接时 status=error 的依据），下线/停用即清除
_ERRORS: dict[str, str] = {}
_LOCK = threading.Lock()


class McpError(Exception):
    """对外可读的 MCP 操作失败。"""


def validate_command(command: str) -> str | None:
    """校验 stdio 启动命令。返回错误文案；None 表示通过（url 模式允许空 command）。"""
    parts = shlex.split(command or "")
    if not parts:
        return None
    if parts[0] not in ALLOWED_COMMANDS:
        return f"command 仅允许以下启动器开头：{', '.join(ALLOWED_COMMANDS)}"
    return None


def build_connection(name: str, command: str = "", url: str = "", env: dict | None = None) -> "McpConnection":
    """构造连接对象。独立工厂函数，测试可替换注入假连接。"""
    return McpConnection(name, command=command, url=url, env=env)


class McpConnection:
    """一个 MCP server 的常驻连接：专属线程 + 事件循环里保持 session 打开。

    error 非 None 即视为不可用（连接失败 / 调用中断线），后续调用短路返回提示，
    不自动重连 —— 避免对故障服务形成重试风暴；由 refresh 接口显式重建。
    """

    def __init__(self, name: str, command: str = "", url: str = "", env: dict | None = None):
        self.name = name
        self.command = (command or "").strip()
        self.url = (url or "").strip()
        self.env = dict(env or {})
        self.error: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session = None                      # ClientSession，仅在专属循环内赋值
        self._ready = threading.Event()           # initialize 完成或失败后置位
        self._stopped: asyncio.Event | None = None

    # ── 生命周期 ─────────────────────────────────────────────────────

    def start(self) -> None:
        """起后台线程并等待 initialize 完成（最多 15s）；失败时抛 McpError。"""
        self._thread = threading.Thread(target=self._run, name=f"mcp-{self.name}", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=15):
            raise McpError(f"MCP 服务 {self.name} 初始化超时")
        if not self.ready:
            raise McpError(self.error or f"MCP 服务 {self.name} 连接失败")

    def stop(self) -> None:
        """通知专属循环退出上下文并回收线程；幂等。"""
        loop, thread = self._loop, self._thread
        if loop is not None and thread is not None and loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._signal_stop(), loop).result(timeout=5)
            except Exception:
                pass
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        self._loop = None
        self._thread = None
        self._session = None

    @property
    def ready(self) -> bool:
        return self._session is not None and self.error is None

    def _open_transport(self):
        """按配置选择传输层，返回 async 上下文管理器（yield (read, write)）。"""
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        if self.url:
            try:  # SDK 新旧版本函数名不同，做兼容
                from mcp.client.streamable_http import streamable_http_client as http_client
            except ImportError:
                from mcp.client.streamable_http import streamablehttp_client as http_client
            return http_client(self.url)
        parts = shlex.split(self.command)
        # SDK 会把 env 合并在精简后的默认环境之上（PATH/HOME 等保留），API key 类变量可直接透传
        return stdio_client(StdioServerParameters(command=parts[0], args=parts[1:], env=self.env))

    async def _serve(self) -> None:
        self._stopped = asyncio.Event()
        try:
            async with self._open_transport() as streams:
                from mcp import ClientSession

                read, write = streams
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session = session
                    self.error = None
                    self._ready.set()
                    await self._stopped.wait()
        except Exception as e:
            self.error = f"MCP 服务 {self.name} 连接失败: {e}"
            logger.warning("%s", self.error)
        finally:
            self._session = None
            self._ready.set()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        finally:
            self._loop.close()

    async def _signal_stop(self) -> None:
        if self._stopped is not None:
            self._stopped.set()

    # ── 同步门面（供 registry 包装函数在任意线程调用）────────────────

    def list_tools(self):
        """列出远端工具；失败时抛异常并标记不可用。"""
        session = self._require_session("list_tools")
        fut = asyncio.run_coroutine_threadsafe(session.list_tools(), self._loop)
        return self._wait(fut)

    def call_tool(self, tool_name: str, arguments: dict):
        """调用远端工具，返回 CallToolResult；任何失败抛异常并把连接标记为不可用。"""
        session = self._require_session(tool_name)
        fut = asyncio.run_coroutine_threadsafe(
            session.call_tool(tool_name, arguments), self._loop
        )
        return self._wait(fut)

    def _require_session(self, action: str):
        if self.error is not None:
            raise McpError(f"MCP 服务 {self.name} 不可用: {self.error}")
        if self._session is None or self._loop is None:
            raise McpError(f"MCP 服务 {self.name} 未连接")
        return self._session

    def _wait(self, fut: concurrent.futures.Future):
        try:
            result = fut.result(timeout=_CALL_TIMEOUT)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            raise McpError(f"MCP 服务 {self.name} 响应超时") from None
        self._check(fut)
        return result

    def _check(self, fut: concurrent.futures.Future) -> None:
        """把执行期异常统一转成 McpError 并标记断线。"""
        exc = fut.exception()
        if exc is not None:
            self.error = f"MCP 服务 {self.name} 不可用: {exc}"
            logger.warning("%s", self.error)
            raise McpError(self.error) from exc


def _result_to_dict(result) -> dict:
    """CallToolResult → registry 统一的 success/result 结构。

    有结构化输出优先用之；否则拼接文本块；is_error=True 转失败路径。
    """
    text_parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        text_parts.append(text if isinstance(text, str) else str(block))
    payload = "\n".join(text_parts)
    if getattr(result, "is_error", False):
        return {"success": False, "error": payload or "MCP 工具返回错误"}
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return {"success": True, "result": structured}
    return {"success": True, "result": payload}


def _registry_name(server: str, tool: str) -> str:
    """生成 mcp_<server>_<tool> 注册名：截到 64 字符，撞名时追加序号。"""
    base = f"mcp_{server}_{tool}"[:MAX_TOOL_NAME_LEN]
    name, i = base, 2
    while name in _REGISTRY:
        suffix = f"_{i}"
        name = base[: MAX_TOOL_NAME_LEN - len(suffix)] + suffix
        i += 1
    return name


def _normalize_parameters(schema) -> dict:
    """inputSchema → OpenAI function parameters；非 object 形状一律回退空对象。"""
    if isinstance(schema, dict) and schema.get("type") == "object":
        return schema
    return {"type": "object", "properties": {}}


def _make_wrapper(server: str, conn: McpConnection, tool: str):
    """生成注册进 _REGISTRY 的同步包装函数（签名与内置工具一致）。

    断线路径：conn 已标记不可用或调用抛错 → 返回 success=False 的「服务不可用」
    提示，不自动重连（防重试风暴），等用户在设置页刷新。
    """

    def wrapper(args: dict, user, db) -> dict:
        if conn.error is not None or not conn.ready:
            return {
                "success": False,
                "error": f"MCP 服务 {server} 不可用，请在设置页刷新该服务后重试",
            }
        try:
            result = conn.call_tool(tool, args)
        except Exception as e:
            return {"success": False, "error": str(e)}
        return _result_to_dict(result)

    return wrapper


def register_server(
    name: str, command: str = "", url: str = "", env: dict | None = None, conn=None
) -> dict:
    """连接 server 并把其全部工具注册进 _REGISTRY（先清理同名旧注册，幂等）。

    返回 {"ok": bool, "tools": [注册名...], "error": str|None}。
    conn 参数供测试注入假连接；缺省经 build_connection 构造真实连接。
    """
    with _LOCK:
        unregister_server(name)
        real = conn if conn is not None else build_connection(name, command, url, env)
        try:
            real.start()
            listing = real.list_tools()
        except Exception as e:
            try:
                real.stop()
            except Exception:
                pass
            # 记录失败原因：配置行保留（enabled），列表接口以 error 态展示，可刷新重试
            _ERRORS[name] = str(e)
            return {"ok": False, "tools": [], "error": str(e)}

        registered: list[str] = []
        for t in getattr(listing, "tools", None) or []:
            reg_name = _registry_name(name, t.name)
            _REGISTRY[reg_name] = {
                "fn": _make_wrapper(name, real, t.name),
                "description": t.description or t.name,
                "parameters": _normalize_parameters(getattr(t, "input_schema", None)),
                "requires_confirm": False,
            }
            registered.append(reg_name)
        _CONNECTIONS[name] = {"conn": real, "tools": registered}
        logger.info("[mcp] %s 上线 %d 个工具: %s", name, len(registered), registered)
        return {"ok": True, "tools": registered, "error": None}


def unregister_server(name: str) -> None:
    """下线 server：注销其全部工具包装并关闭连接、清除错误标记。幂等。"""
    _ERRORS.pop(name, None)
    entry = _CONNECTIONS.pop(name, None)
    if entry is None:
        return
    for reg_name in entry["tools"]:
        _REGISTRY.pop(reg_name, None)
    try:
        entry["conn"].stop()
    except Exception as e:
        logger.warning("[mcp] 关闭 %s 连接异常(忽略): %s", name, e)


def connection_status(name: str) -> str:
    """connected / error / off 三态，供列表接口展示。"""
    entry = _CONNECTIONS.get(name)
    if entry is None:
        # 无存活连接：最近一次连接失败过则报 error（配置保留待刷新），否则视为未连接
        return "error" if name in _ERRORS else "off"
    conn = entry["conn"]
    if conn.error is not None or not conn.ready:
        return "error"
    return "connected"


def registered_tools(name: str) -> list[str]:
    return list(_CONNECTIONS.get(name, {}).get("tools", []))


def startup_connect(db) -> int:
    """启动接线：对 enabled 的全局 server（user_id 为空）逐个 connect。

    单个失败只 log 不抛，绝不拖垮应用启动。
    """
    from .models import McpServer

    n = 0
    for row in (
        db.query(McpServer).filter(McpServer.enabled == 1, McpServer.user_id.is_(None)).all()
    ):
        outcome = register_server(row.name, row.command, row.url, _parse_env(row.env_json))
        if outcome["ok"]:
            n += 1
        else:
            logger.warning("[mcp] 启动连接 %s 失败(跳过): %s", row.name, outcome["error"])
    return n


def shutdown_all() -> None:
    """停机时关闭所有连接。"""
    for name in list(_CONNECTIONS):
        unregister_server(name)


def _parse_env(env_json: str) -> dict:
    """env_json 列 → dict；坏 JSON / 非对象一律回退空环境。"""
    try:
        data = json.loads(env_json or "{}")
    except Exception:
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
