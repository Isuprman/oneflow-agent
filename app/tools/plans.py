# 长程任务规划工具 — 贾维斯在对话中创建/推进跨会话的大目标
#
# 推进三层：对话续接（engine 注入 active 计划摘要 + 用户说「继续」）、
# 每日自动推进一步（jobs/plan_advancer）、用户随时暂停/放弃（set_plan_status）。
from ..models import LongTermPlan, PlanStep
from .registry import tool

MAX_STEPS = 20
STEP_STATUSES = ("todo", "doing", "done", "blocked")
PLAN_STATUSES = ("active", "paused", "done", "cancelled")


def _owned_plan(db, user, plan_id: int) -> LongTermPlan | None:
    return (
        db.query(LongTermPlan)
        .filter(LongTermPlan.id == plan_id, LongTermPlan.user_id == user.id)
        .first()
    )


def load_active_plans_summary(db, user_id: int) -> str:
    """active 计划摘要（注入 system prompt 供对话续接）：标题/进度/下一步/最近备注。"""
    plans = (
        db.query(LongTermPlan)
        .filter(LongTermPlan.user_id == user_id, LongTermPlan.status == "active")
        .order_by(LongTermPlan.id)
        .all()
    )
    if not plans:
        return ""
    lines: list[str] = []
    for plan in plans:
        steps = (
            db.query(PlanStep)
            .filter(PlanStep.plan_id == plan.id)
            .order_by(PlanStep.idx)
            .all()
        )
        done = sum(1 for s in steps if s.status == "done")
        next_step = next((s for s in steps if s.status in ("todo", "doing")), None)
        recent_note = next(
            (s.note for s in reversed(steps) if s.status == "done" and s.note), ""
        )
        line = f"- 《{plan.title}》：{done}/{len(steps)} 步已完成"
        if next_step is not None:
            line += f"，下一步：{next_step.description}"
        if recent_note:
            line += f"；最近进展：{recent_note[:80]}"
        lines.append(line)
    return "\n".join(lines)


@tool(
    name="create_plan",
    description=(
        "创建一个跨会话的长期计划：把用户的大目标拆成有序步骤（≤20 步），"
        "每天会自动推进一步并向用户汇报。用户表达「帮我准备/规划/跟进一个持续多天的目标」时调用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "计划短标题，如「11月考证备考」"},
            "goal": {"type": "string", "description": "目标的完整描述（验收标准）"},
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "有序步骤列表，每步一条可独立执行的描述",
            },
        },
        "required": ["title", "goal", "steps"],
    },
)
def create_plan(args: dict, user, db):
    title = (args.get("title") or "").strip()
    goal = (args.get("goal") or "").strip()
    steps = [str(s).strip() for s in (args.get("steps") or []) if str(s).strip()]
    if not title or not steps:
        return {"success": False, "error": "标题与步骤均不能为空"}
    if len(steps) > MAX_STEPS:
        return {"success": False, "error": f"步骤最多 {MAX_STEPS} 条，请合并细化"}
    plan = LongTermPlan(user_id=user.id, title=title, goal=goal, status="active")
    db.add(plan)
    db.commit()
    db.refresh(plan)
    for idx, desc in enumerate(steps):
        db.add(PlanStep(plan_id=plan.id, idx=idx, description=desc))
    db.commit()
    return {"success": True, "plan_id": plan.id, "title": title, "steps": steps}


@tool(
    name="update_plan_step",
    description="更新长期计划的步骤状态：开始/完成/阻塞某一步，可附一句话进展备注。",
    parameters={
        "type": "object",
        "properties": {
            "plan_id": {"type": "integer", "description": "计划 id"},
            "idx": {"type": "integer", "description": "步骤序号（从 0 开始）"},
            "status": {"type": "string", "enum": list(STEP_STATUSES), "description": "新状态"},
            "note": {"type": "string", "description": "一句话进展备注（可选）"},
        },
        "required": ["plan_id", "idx", "status"],
    },
)
def update_plan_step(args: dict, user, db):
    plan = _owned_plan(db, user, int(args.get("plan_id") or 0))
    if plan is None:
        return {"success": False, "error": "计划不存在"}
    status = args.get("status")
    if status not in STEP_STATUSES:
        return {"success": False, "error": f"步骤状态必须是 {'/'.join(STEP_STATUSES)}"}
    raw_idx = args.get("idx")
    idx = -1 if raw_idx is None else int(raw_idx)  # idx=0 是合法值，不能用 or 兜底
    step = (
        db.query(PlanStep)
        .filter(PlanStep.plan_id == plan.id, PlanStep.idx == idx)
        .first()
    )
    if step is None:
        return {"success": False, "error": "步骤不存在"}
    step.status = status
    if args.get("note"):
        step.note = str(args["note"])[:300]
    db.commit()
    return {"success": True, "plan_id": plan.id, "idx": step.idx, "status": step.status}


@tool(name="list_plans", description="列出用户的所有长期计划及各步骤状态。", parameters={"type": "object", "properties": {}})
def list_plans(args: dict, user, db):
    plans = (
        db.query(LongTermPlan)
        .filter(LongTermPlan.user_id == user.id)
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
        result.append(
            {
                "plan_id": plan.id,
                "title": plan.title,
                "goal": plan.goal,
                "status": plan.status,
                "steps": [
                    {"idx": s.idx, "description": s.description, "status": s.status, "note": s.note}
                    for s in steps
                ],
            }
        )
    return {"success": True, "plans": result}


@tool(
    name="set_plan_status",
    description="设置计划整体状态：active 进行 / paused 暂停 / done 完成 / cancelled 放弃。",
    parameters={
        "type": "object",
        "properties": {
            "plan_id": {"type": "integer", "description": "计划 id"},
            "status": {"type": "string", "enum": list(PLAN_STATUSES)},
        },
        "required": ["plan_id", "status"],
    },
)
def set_plan_status(args: dict, user, db):
    plan = _owned_plan(db, user, int(args.get("plan_id") or 0))
    if plan is None:
        return {"success": False, "error": "计划不存在"}
    status = args.get("status")
    if status not in PLAN_STATUSES:
        return {"success": False, "error": f"计划状态必须是 {'/'.join(PLAN_STATUSES)}"}
    plan.status = status
    db.commit()
    return {"success": True, "plan_id": plan.id, "status": plan.status}
