# 数字分身：外出规则由 LLM 判定此刻是否需要动作（如日程变更），
# 是则执行并留「数字分身代劳」通知；每规则每天最多动作一次（限流在 learn/companion 内）。
async def run(db, now) -> None:
    from ..learn.companion import run_away_rules

    await run_away_rules(db)
