# 反向面试：对每个用户做每周最多一次的画像补全提问（每周节流在 learn/interview 内）。
from ..models import User


async def run(db, now) -> None:
    await run_interviews(db)


async def run_interviews(db) -> list[str]:
    """反向面试：对每个用户做每周最多一次的画像补全提问。

    仅 should_interview 通过时才生成+投递；单人异常回滚跳过，不拖垮其他用户。
    """
    from ..learn.interview import deliver, generate_question, should_interview
    from ..user_cfg import get_llm_map

    summaries: list[str] = []
    for user in db.query(User).all():
        try:
            if not should_interview(db, user.id):
                continue
            cfg_map = get_llm_map(db, user.id)
            if not cfg_map.get("llm.api_key"):
                continue
            cfg = {"provider": cfg_map.get("llm.provider"), "model": cfg_map.get("llm.model"),
                   "api_key": cfg_map.get("llm.api_key"), "base_url": cfg_map.get("llm.base_url")}
            question = await generate_question(db, user, cfg)
            if not question:
                continue
            deliver(db, user.id, question)
            summaries.append(f"user{user.id}: {question[:40]}")
        except Exception:
            db.rollback()
    return summaries
