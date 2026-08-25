# OneFlow 成长日记路由 — 聚合自学习提案与工具调用流水，输出贾维斯的成长档案
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Conversation, SkillProposal, ToolCallLog, User

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("")
def growth_journal(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """成长档案聚合：首个技能、学会/放弃计数、里程碑时间线、累计工具调用次数。"""
    uid = current_user.id

    learned_count = (
        db.query(func.count(SkillProposal.id))
        .filter(SkillProposal.user_id == uid, SkillProposal.status == "approved")
        .scalar()
    )
    rejected_count = (
        db.query(func.count(SkillProposal.id))
        .filter(SkillProposal.user_id == uid, SkillProposal.status == "rejected")
        .scalar()
    )

    # 全部 approved 提案按时间升序 = 里程碑时间线；最早的一条即第一个技能
    approved = (
        db.query(SkillProposal)
        .filter(SkillProposal.user_id == uid, SkillProposal.status == "approved")
        .order_by(SkillProposal.created_at.asc(), SkillProposal.id.asc())
        .all()
    )
    milestones = [
        {"date": p.created_at.isoformat() if p.created_at else None, "title": p.title or p.slug}
        for p in approved
    ]
    first_skill = milestones[0] if milestones else None

    # 工具调用流水挂在会话上，经 conversation 归属到用户
    total_tool_calls = (
        db.query(func.count(ToolCallLog.id))
        .join(Conversation, ToolCallLog.conversation_id == Conversation.id)
        .filter(Conversation.user_id == uid)
        .scalar()
    )

    return {
        "first_skill": first_skill,
        "learned_count": int(learned_count or 0),
        "rejected_count": int(rejected_count or 0),
        "milestones": milestones,
        "total_tool_calls": int(total_tool_calls or 0),
    }
