# OneFlow FastAPI 入口
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import inspect, text

from .config import settings
from .db import Base, engine, SessionLocal
from . import models  # noqa: F401  确保建表前模型已注册


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _migrate_messages_reasoning()
    _migrate_schedules_notified()
    _migrate_user_memories_embedding()
    # 后台调度引擎：定时任务执行 + 日程到期提醒（测试环境不启动，避免干扰）
    import sys

    scheduler = None
    if "pytest" not in sys.modules:
        from .scheduler import start_scheduler, shutdown_scheduler

        scheduler = start_scheduler()
    try:
        yield
    finally:
        if scheduler is not None:
            from .scheduler import shutdown_scheduler

            shutdown_scheduler(scheduler)


app = FastAPI(title="OneFlow", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_provider": settings.llm_provider, "llm_model": settings.llm_model}


from .routers import auth, briefing, chat, chat_stream, conversations, memories, notifications, tts
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
