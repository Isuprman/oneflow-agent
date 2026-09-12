# 上线技能质量反馈环（差评自动降级 / 好评一次性通知）；统计窗口在 learn/habit 内。
async def run(db, now) -> None:
    from ..learn.habit import run_skill_quality_check

    # 原实现误用 asyncio.run（在运行中的事件循环内必然 RuntimeError，任务从未真正跑过），改为 await
    await run_skill_quality_check(db)
