# 技能市场路由 — 浏览 / 安装 / 导出 已上线技能
# 已上线 = 任意用户 status=approved 的提案；安装走既有门禁+沙箱重验，复用 learn.service 逻辑。
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..learn import service
from ..models import SkillProposal, User

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/skills")
def list_skills(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出所有用户已上线（approved）的技能：slug / description / 作者名。"""
    rows = (
        db.query(SkillProposal)
        .filter(SkillProposal.status == "approved")
        .order_by(SkillProposal.id.desc())
        .all()
    )
    author_ids = {p.user_id for p in rows}
    authors: dict[int, str] = {}
    if author_ids:
        authors = {u.id: u.username for u in db.query(User).filter(User.id.in_(author_ids)).all()}
    return [
        {
            "id": p.id,
            "slug": p.slug,
            "title": p.title,
            "description": p.description,
            "author": authors.get(p.user_id, ""),
        }
        for p in rows
    ]


@router.get("/skills/{skill_id}/export")
def export_skill(
    skill_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """导出技能 JSON 包：code / tests / description。"""
    proposal = _approved(db, skill_id)
    return {
        "id": proposal.id,
        "slug": proposal.slug,
        "title": proposal.title,
        "description": proposal.description,
        "code": proposal.tool_code,
        "tests": proposal.test_code,
    }


@router.post("/skills/{skill_id}/install")
def install_skill(
    skill_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """安装他人技能：门禁+沙箱重验 → 复制为本用户提案 → 批准上线。"""
    source = _approved(db, skill_id)
    try:
        proposal = service.install_skill(db, current_user, source)
    except service.LearnError as e:
        raise HTTPException(422, str(e))
    required = json.loads(proposal.required_keys or "{}")
    return {
        "id": proposal.id,
        "slug": proposal.slug,
        "title": proposal.title,
        "description": proposal.description,
        "status": proposal.status,
        "required_keys": required,
        "message": "技能已上线" if proposal.status == "approved" else "已创建提案，请在技能列表补齐所需 key 后批准",
    }


def _approved(db: Session, skill_id: int) -> SkillProposal:
    proposal = db.query(SkillProposal).filter_by(id=skill_id).first()
    if proposal is None or proposal.status != "approved":
        raise HTTPException(404, "技能不存在")
    return proposal
