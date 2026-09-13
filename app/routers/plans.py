# 长程计划路由 — 列表 / 状态变更（步骤推进走 agent 工具，不在这层）
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import LongTermPlan, PlanStep, User
from ..tools.plans import PLAN_STATUSES

router = APIRouter(prefix="/api/plans", tags=["plans"])


class PlanStepOut(BaseModel):
    idx: int
    description: str
    status: str
    note: Optional[str] = None


class PlanOut(BaseModel):
    id: int
    title: str
    goal: str
    status: str
    steps: List[PlanStepOut]
    created_at: Optional[str] = None


class PlanStatusIn(BaseModel):
    status: str


def _to_out(plan: LongTermPlan, steps: List[PlanStep]) -> PlanOut:
    return PlanOut(
        id=plan.id,
        title=plan.title,
        goal=plan.goal,
        status=plan.status,
        steps=[
            PlanStepOut(idx=s.idx, description=s.description, status=s.status, note=s.note)
            for s in steps
        ],
        created_at=plan.created_at.isoformat() if plan.created_at else None,
    )


@router.get("", response_model=List[PlanOut])
def list_plans(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plans = (
        db.query(LongTermPlan)
        .filter(LongTermPlan.user_id == current_user.id)
        .order_by(LongTermPlan.id.desc())
        .all()
    )
    result = []
    for plan in plans:
        steps = (
            db.query(PlanStep)
            .filter(PlanStep.plan_id == plan.id)
            .order_by(PlanStep.idx)
            .all()
        )
        result.append(_to_out(plan, steps))
    return result


@router.put("/{plan_id}/status", response_model=PlanOut)
def set_plan_status(
    plan_id: int,
    body: PlanStatusIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = (
        db.query(LongTermPlan)
        .filter(LongTermPlan.id == plan_id, LongTermPlan.user_id == current_user.id)
        .first()
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="计划不存在")
    if body.status not in PLAN_STATUSES:
        raise HTTPException(status_code=400, detail=f"状态必须是 {'/'.join(PLAN_STATUSES)}")
    plan.status = body.status
    db.commit()
    db.refresh(plan)
    steps = db.query(PlanStep).filter(PlanStep.plan_id == plan.id).order_by(PlanStep.idx).all()
    return _to_out(plan, steps)
