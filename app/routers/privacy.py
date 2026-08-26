# OneFlow 数据主权路由 — 导出 / 清除
# 导出：聚合该用户 memories / profile / conversations+messages / skill_proposals / tasks 为单份 JSON。
# 清除：真删该用户全部数据（按外键层级自下而上），返回 {表: 行数} 收据；需 body {"confirm": "DELETE"} 防误触。
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import (
    Conversation,
    CustomAgent,
    Expense,
    HabitDismissed,
    LearnKey,
    LearnSkillEmbedding,
    McpServer,
    Message,
    Notification,
    PendingAction,
    Schedule,
    ScheduledTask,
    Scene,
    SkillProposal,
    TokenUsage,
    ToolCallLog,
    User,
    UserMemory,
    UserProfile,
    UserSetting,
)

router = APIRouter(prefix="/api/privacy", tags=["privacy"])

EXPORT_VERSION = 1


def _iso(v):
    """datetime/None → ISO 字符串，保证可 JSON 序列化。"""
    return v.isoformat() if v is not None else None


def _parse_json(text):
    if not text:
        return {}
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return {}


# ─── GET /api/privacy/export ─────────────────────────────────────────


@router.get("/export")
def export_data(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """导出当前用户全部数据为单份 JSON（含版本号与生成时间戳）。"""
    uid = current_user.id

    memories = [
        {
            "id": m.id,
            "content": m.content,
            "created_at": _iso(m.created_at),
            "updated_at": _iso(m.updated_at),
        }
        for m in db.query(UserMemory).filter(UserMemory.user_id == uid).order_by(UserMemory.id).all()
    ]

    profile = [
        {"key": p.key, "value": p.value}
        for p in db.query(UserProfile).filter(UserProfile.user_id == uid).order_by(UserProfile.id).all()
    ]

    conv_rows = (
        db.query(Conversation).filter(Conversation.user_id == uid).order_by(Conversation.id).all()
    )
    conversations = []
    for c in conv_rows:
        messages = [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "tool_call": m.tool_call,
                "reasoning_content": m.reasoning_content,
                "created_at": _iso(m.created_at),
            }
            for m in db.query(Message).filter(Message.conversation_id == c.id).order_by(Message.id).all()
        ]
        tool_calls = [
            {
                "id": t.id,
                "tool_name": t.tool_name,
                "arguments": _parse_json(t.arguments),
                "result": _parse_json(t.result),
                "success": bool(t.success),
                "created_at": _iso(t.created_at),
            }
            for t in db.query(ToolCallLog).filter(ToolCallLog.conversation_id == c.id).order_by(ToolCallLog.id).all()
        ]
        conversations.append(
            {
                "id": c.id,
                "title": c.title,
                "created_at": _iso(c.created_at),
                "messages": messages,
                "tool_calls": tool_calls,
            }
        )

    skill_proposals = [
        {
            "id": p.id,
            "slug": p.slug,
            "title": p.title,
            "description": p.description,
            "status": p.status,
            "tool_code": p.tool_code,
            "test_code": p.test_code,
            "test_output": p.test_output,
            "required_keys": _parse_json(p.required_keys),
            "branch": p.branch,
            "created_at": _iso(p.created_at),
        }
        for p in db.query(SkillProposal).filter(SkillProposal.user_id == uid).order_by(SkillProposal.id).all()
    ]

    tasks = [
        {
            "id": t.id,
            "title": t.title,
            "instruction": t.instruction,
            "kind": t.kind,
            "hour": t.hour,
            "minute": t.minute,
            "weekday": t.weekday,
            "run_at": _iso(t.run_at),
            "enabled": bool(t.enabled),
            "next_run_at": _iso(t.next_run_at),
            "created_at": _iso(t.created_at),
        }
        for t in db.query(ScheduledTask).filter(ScheduledTask.user_id == uid).order_by(ScheduledTask.id).all()
    ]

    return {
        "format": "oneflow-user-export",
        "version": EXPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user": {"id": current_user.id, "username": current_user.username},
        "memories": memories,
        "profile": profile,
        "conversations": conversations,
        "skill_proposals": skill_proposals,
        "tasks": tasks,
    }


# ─── DELETE /api/privacy/purge ───────────────────────────────────────


class PurgeConfirm(BaseModel):
    confirm: str


# 按外键层级自下而上删除：messages/tool_calls_log 挂在 conversation 下，
# pending_actions 挂 conversation_id，须先于 conversations 清掉。
_PURGE_TABLES = [
    ("user_settings", UserSetting),
    ("user_memories", UserMemory),
    ("user_profiles", UserProfile),
    ("skill_proposals", SkillProposal),
    ("scheduled_tasks", ScheduledTask),
    ("expenses", Expense),
    ("schedules", Schedule),
    ("notifications", Notification),
    ("custom_agents", CustomAgent),
    ("learn_keys", LearnKey),
    ("habit_dismissed", HabitDismissed),
    ("learn_skill_embeddings", LearnSkillEmbedding),
    ("token_usages", TokenUsage),
    ("scenes", Scene),
    # mcp_servers 的 user_id 可空：NULL = 全局共享，仅清当前用户的私有行
    ("mcp_servers", McpServer),
]


@router.delete("/purge")
def purge_data(
    body: PurgeConfirm,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """真删当前用户全部数据，返回删除收据 {表: 行数}。需 body {"confirm": "DELETE"}。"""
    if body.confirm != "DELETE":
        raise HTTPException(status_code=400, detail='请携带 body {"confirm": "DELETE"} 确认清除')
    uid = current_user.id
    conv_ids = db.query(Conversation.id).filter(Conversation.user_id == uid)
    receipt = {}
    try:
        # 会话子表先清（依赖 conversation_id，仅本用户会话范围）
        receipt["messages"] = (
            db.query(Message).filter(Message.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
        )
        receipt["tool_calls_log"] = (
            db.query(ToolCallLog).filter(ToolCallLog.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
        )
        receipt["pending_actions"] = (
            db.query(PendingAction).filter(PendingAction.user_id == uid).delete(synchronize_session=False)
        )
        receipt["conversations"] = (
            db.query(Conversation).filter(Conversation.user_id == uid).delete(synchronize_session=False)
        )
        # 其余用户级表：按 user_id 直删
        for table_name, model in _PURGE_TABLES:
            count = db.query(model).filter(model.user_id == uid).delete(synchronize_session=False)
            if count:
                receipt[table_name] = count
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"purged_user_id": uid, "receipt": receipt}
