# OneFlow FastAPI 入口
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text

from .config import settings
from .db import Base, engine, SessionLocal
from . import models  # noqa: F401  确保建表前模型已注册

# 前端构建产物（npm run build）；存在时由 FastAPI 托管，Electron 壳直接加载 :8020
_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _migrate_messages_reasoning() -> None:
    """老库补齐 messages.reasoning_content 列（create_all 不会给已有表加列）。

    思考模型（deepseek-reasoner 等）要求多轮回传思维链，此列用于持久化。
    """
    inspector = inspect(engine)
    if "messages" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("messages")}
    if "reasoning_content" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE messages ADD COLUMN reasoning_content TEXT"))


def _migrate_schedules_notified() -> None:
    """老库补齐 schedules.notified 列：日程到期提醒的防重复标记。"""
    inspector = inspect(engine)
    if "schedules" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("schedules")}
    if "notified" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE schedules ADD COLUMN notified INTEGER DEFAULT 0"))


def _migrate_user_memories_embedding() -> None:
    """老库补齐 user_memories.embedding 列：语义召回的向量存储。"""
    inspector = inspect(engine)
    if "user_memories" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("user_memories")}
    if "embedding" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE user_memories ADD COLUMN embedding TEXT"))


def _migrate_user_memories_cognition() -> None:
    """老库补齐 user_memories.status / last_accessed 列：冲突消解标记与遗忘衰减。"""
    inspector = inspect(engine)
    if "user_memories" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("user_memories")}
    with engine.begin() as conn:
        if "status" not in columns:
            conn.execute(text("ALTER TABLE user_memories ADD COLUMN status TEXT DEFAULT 'active'"))
        if "last_accessed" not in columns:
            conn.execute(text("ALTER TABLE user_memories ADD COLUMN last_accessed DATETIME"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _migrate_messages_reasoning()
    _migrate_schedules_notified()
    _migrate_user_memories_embedding()
    _migrate_user_memories_cognition()
    # 自学习工具的外部 key 回注进程环境（重启后技能仍能取到 key）
    from .learn.service import inject_saved_keys

    with SessionLocal() as _db:
        try:
            inject_saved_keys(_db)
        except Exception as _e:  # key 注入失败不阻断启动
            print(f"[learn] 启动注入工具 key 失败(忽略): {_e}")
    # 后台调度引擎：定时任务执行 + 日程到期提醒（测试环境不启动，避免干扰）
    import sys

    scheduler = None
    mcp_cleanup = None
    if "pytest" not in sys.modules:
        from .scheduler import start_scheduler, shutdown_scheduler

        scheduler = start_scheduler()

        # MCP 全局服务预连接：单个失败只 log，不拖垮启动（测试环境同样跳过）
        from .mcp_client import shutdown_all as mcp_cleanup
        from .mcp_client import startup_connect as mcp_startup_connect

        with SessionLocal() as _mcp_db:
            try:
                mcp_startup_connect(_mcp_db)
            except Exception as _e:  # noqa: S110  MCP 故障不影响主流程
                print(f"[mcp] 启动连接失败(忽略): {_e}")
    try:
        yield
    finally:
        if scheduler is not None:
            from .scheduler import shutdown_scheduler

            shutdown_scheduler(scheduler)
        if mcp_cleanup is not None:
            mcp_cleanup()


app = FastAPI(title="OneFlow", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_provider": settings.llm_provider, "llm_model": settings.llm_model}


from .routers import auth, briefing, chat, chat_stream, conversations, idle_hint, memories, notifications, tasks, tts, usage
from .routers import learn as learn_router
from .routers import mcp as mcp_router
from .routers import scenes as scenes_router
from .routers import settings as settings_router  # noqa: E402,F401

app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(chat_stream.router)
app.include_router(settings_router.router)
app.include_router(tts.router)
app.include_router(memories.router)
app.include_router(notifications.router)
app.include_router(briefing.router)
app.include_router(tasks.router)
app.include_router(idle_hint.router)
app.include_router(learn_router.router)
app.include_router(mcp_router.router)
app.include_router(scenes_router.router)
app.include_router(usage.router)
from .routers import journal as journal_router
app.include_router(journal_router.router)
from .routers import privacy as privacy_router
app.include_router(privacy_router.router)

# ---- 前端静态托管（仅在存在构建产物时启用，不影响纯 API 开发模式）----
if (_FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="static-assets")


@app.middleware("http")
async def spa_fallback(request, call_next):
    """SPA 回退：非 API 路径的 404 优先返回同名静态文件，其次返回 index.html。

    用中间件而非 catch-all 路由：后者会吞掉 Starlette 对 /api/xxx/ 尾斜杠的
    307 重定向，导致 POST 带斜杠路径变 405。
    """
    response = await call_next(request)
    if response.status_code != 404 or request.url.path.startswith("/api"):
        return response
    if _FRONTEND_DIST.is_dir():
        rel = request.url.path.lstrip("/")
        if rel:
            candidate = (_FRONTEND_DIST / rel).resolve()
            if _FRONTEND_DIST in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
        index = _FRONTEND_DIST / "index.html"
        if index.is_file():
            return FileResponse(index)
    return response
