# 长程计划每日自动推进 — 每计划每天一步，产出「计划推进」通知
#
# 在用户专属的「计划推进」会话里跑一遍 agent（复用定时任务模式）：
# 先占位 last_advanced_at 再执行，防长任务期间重复推进；单计划失败回滚跳过。
from datetime import datetime

from ..models import Conversation, LongTermPlan, Notification, User

PLAN_CONVERSATION_TITLE = "计划推进"


async def run(db, now: datetime) -> None:
    plans = db.query(LongTermPlan).filter(LongTermPlan.status == "active").all()
    for plan in plans:
        try:
            if plan.last_advanced_at is not None and plan.last_advanced_at.date() == now.date():
                continue
            plan.last_advanced_at = now
            db.commit()

            user = db.get(User, plan.user_id)
            if user is None:
                continue
            conv = (
                db.query(Conversation)
                .filter(Conversation.user_id == user.id, Conversation.title == PLAN_CONVERSATION_TITLE)
                .first()
            )
            if conv is None:
                conv = Conversation(user_id=user.id, title=PLAN_CONVERSATION_TITLE)
                db.add(conv)
                db.commit()
                db.refresh(conv)

            instruction = (
                f"请推进长期计划《{plan.title}》（目标：{plan.goal}）的下一步。"
                "先调用 list_plans 查看当前步骤，然后推进下一步（优先不产生需要确认的写操作），"
                "用 update_plan_step 记录状态与一句话备注；"
                "若全部步骤已完成，调用 set_plan_status 置为 done。"
                "最后用一两句话向先生汇报今天的进展。"
            )
            from ..agent.engine import run_agent

            try:
                reply, _steps, _trace = await run_agent(db, user, conv.id, instruction)
            except Exception as e:  # 任务失败也要告知用户，而不是静默吞掉
                reply = f"计划推进失败: {e}"
            db.add(
                Notification(
                    user_id=user.id,
                    title=f"计划推进：{plan.title}",
                    content=reply,
                    kind="plan",
                )
            )
            db.commit()
        except Exception:
            db.rollback()
            continue
