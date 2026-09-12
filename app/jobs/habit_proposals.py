# 习惯 → 技能提案（经验结晶，走既有审批流）；限流与去重在 learn/habit 内。
async def run(db, now) -> None:
    from ..learn.habit import run_daily_proposals

    # 原实现误用 asyncio.run（在运行中的事件循环内必然 RuntimeError，任务从未真正跑过），改为 await
    await run_daily_proposals(db)
