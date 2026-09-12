# 记忆召回：语义相似度 × 时间衰减排序；无向量时回退最近度排序。
# 读时更新 last_accessed（重置衰减）；闲置超 90 天且衰减后权重过低的记忆不再注入。
import math
from datetime import datetime, timezone

from ..models import UserMemory

# 记忆遗忘衰减：召回分数乘 exp(-闲置天数/120)；闲置超 90 天且权重低于阈值的不再注入
MEMORY_DECAY_DAYS = 120
MEMORY_STALE_DAYS = 90
MEMORY_MIN_WEIGHT = 0.05


def _memory_idle_days(m, now: datetime) -> int:
    """记忆闲置天数：自上次访问算起（从未访问则按更新时间），时区缺失按 UTC 处理。"""
    ref = m.last_accessed or m.updated_at or m.created_at
    if ref is None:
        return 0
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return max(0, (now - ref).days)


def _memory_decay(idle_days: int) -> float:
    """衰减系数 exp(-闲置天数/120)：越久没被想起，权重越低。"""
    return math.exp(-idle_days / MEMORY_DECAY_DAYS)


async def _recall_memories(db, user, user_msg: str, cfg) -> list[str]:
    """记忆召回：语义相似度 × 时间衰减排序；无向量时回退最近度排序。

    读时更新 last_accessed（重置衰减）；闲置超 90 天且衰减后权重过低的记忆不再注入。
    """
    from .embed import cosine, embed_text, json_to_embedding

    rows = (
        db.query(UserMemory)
        .filter(UserMemory.user_id == user.id, UserMemory.status == "active")
        .order_by(UserMemory.updated_at.desc())
        .limit(50)
        .all()
    )
    if not rows:
        return []
    now = datetime.now(timezone.utc)
    query_vec = await embed_text(user_msg, cfg)

    scored = []
    semantic = query_vec is not None and any(json_to_embedding(m.embedding) for m in rows)
    if semantic:
        for m in rows:
            vec = json_to_embedding(m.embedding)
            if vec is None:
                continue
            idle = _memory_idle_days(m, now)
            score = cosine(query_vec, vec) * _memory_decay(idle)
            if idle > MEMORY_STALE_DAYS and score < MEMORY_MIN_WEIGHT:
                continue
            scored.append((score, m))
    if not scored:
        # 回退：无查询向量 / 记忆全无向量 → 按衰减后的最近度排序
        for m in rows:
            idle = _memory_idle_days(m, now)
            decay = _memory_decay(idle)
            if idle > MEMORY_STALE_DAYS and decay < MEMORY_MIN_WEIGHT:
                continue
            scored.append((decay, m))

    if not scored:
        return []
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [m for _score, m in scored[: (5 if semantic else 20)]]

    # 读时更新 last_accessed（遗忘衰减的「被想起」信号）
    stamp = datetime.now(timezone.utc)
    for m in selected:
        m.last_accessed = stamp
    db.commit()
    return [m.content for m in selected]
