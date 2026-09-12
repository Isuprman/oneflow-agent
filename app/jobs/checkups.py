# 年度体检：每周最多一次，抽样金题 + 直接重放打分 + 通知（周节流在 learn/checkup 内）。
async def run(db, now) -> None:
    from ..learn.checkup import run_weekly_checkups

    run_weekly_checkups(db)
