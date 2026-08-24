# 自学习路由 — 获取新能力的 API：提案/列表/批准/拒绝
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..learn import service
from ..models import SkillProposal, User
from ..user_cfg import get_llm_map, llm_configured

router = APIRouter(prefix="/api/learn", tags=["learn"])


class AcquireIn(BaseModel):
    request: str


class ApproveIn(BaseModel):
    keys: dict[str, str] = {}


def _to_out(p: SkillProposal) -> dict:
    return {
        "id": p.id,
        "slug": p.slug,
        "title": p.title,
        "description": p.description,
        "status": p.status,
        "required_keys": json.loads(p.required_keys or "{}"),
        "branch": p.branch,
        "log": p.test_output,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.post("/acquire")
def acquire(
    body: AcquireIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """对贾维斯说「你要是能X就好了」的落点：构建候选工具（生成→门禁→沙箱→分支）。"""
    if not body.request.strip():
        raise HTTPException(400, "需求描述不能为空")
    # 费用门禁：构建必须用请求用户自己的 LLM 配置，绝不回落到全局默认 key
    if not llm_configured(db, current_user.id):
        raise HTTPException(400, "未配置 LLM：请先在「设置」页填写你的 LLM 密钥")
    cfg_map = get_llm_map(db, current_user.id)
    cfg = {
        "provider": cfg_map.get("llm.provider"),
        "model": cfg_map.get("llm.model"),
        "api_key": cfg_map.get("llm.api_key"),
        "base_url": cfg_map.get("llm.base_url"),
    }
    duplicate = service.find_duplicate(db, current_user.id, body.request) is not None
    try:
        proposal = service.build_proposal(db, current_user, body.request.strip(), cfg)
    except service.LearnError as e:
        raise HTTPException(429, str(e))
    return {**_to_out(proposal), "duplicate": duplicate}


@router.get("/proposals")
def list_proposals(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(SkillProposal)
        .filter(SkillProposal.user_id == current_user.id)
        .order_by(SkillProposal.id.desc())
        .limit(50)
        .all()
    )
    return [_to_out(p) for p in rows]


@router.post("/proposals/{proposal_id}/approve")
def approve_proposal(
    proposal_id: int,
    body: ApproveIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proposal = db.query(SkillProposal).filter_by(id=proposal_id).first()
    if not proposal:
        raise HTTPException(404, "提案不存在")
    try:
        result = service.approve_proposal(db, current_user, proposal, body.keys)
    except service.LearnError as e:
        raise HTTPException(400, str(e))
    if not result.get("ok"):
        return result  # 缺 key：返回 {ok: False, missing_keys}
    return {"ok": True, "message": f"技能 {proposal.slug} 已上线", **result}


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(
    proposal_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proposal = db.query(SkillProposal).filter_by(id=proposal_id).first()
    if not proposal:
        raise HTTPException(404, "提案不存在")
    try:
        service.reject_proposal(db, current_user, proposal)
    except service.LearnError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "message": "已拒绝并清理"}
