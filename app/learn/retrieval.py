# 技能库向量检索 — 已学技能的语义索引，相似请求复用而非重建
# 存储：LearnSkillEmbedding（每用户一行/技能，JSON 向量）；检索：纯 Python 余弦相似度。
import json

from sqlalchemy.orm import Session

from ..agent.embed import embed_text, json_to_embedding
from ..models import LearnSkillEmbedding


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


async def index_skill(db: Session, user_id: int, slug: str, description: str, cfg: dict | None) -> bool:
    """技能上线时建立/刷新向量索引。返回是否成功。"""
    text = f"{slug} {description}".strip()
    vector = await embed_text(text, cfg)
    if not vector:
        return False
    row = db.query(LearnSkillEmbedding).filter_by(user_id=user_id, slug=slug).first()
    if row:
        row.description = description
        row.embedding = json.dumps(vector)
    else:
        db.add(LearnSkillEmbedding(
            user_id=user_id, slug=slug, description=description,
            embedding=json.dumps(vector),
        ))
    db.commit()
    return True


async def search_similar(
    db: Session, user_id: int, query_text: str, cfg: dict | None, top_k: int = 3,
) -> list[dict]:
    """语义检索已学技能。返回 [{slug, description, score}]，按相似度降序；索引为空返回 []。"""
    query_vec = await embed_text(query_text.strip(), cfg)
    if not query_vec:
        return []
    rows = db.query(LearnSkillEmbedding).filter_by(user_id=user_id).all()
    scored = []
    for row in rows:
        vec = json_to_embedding(row.embedding)
        score = _cosine(query_vec, vec or [])
        scored.append({"slug": row.slug, "description": row.description, "score": round(score, 4)})
    scored.sort(key=lambda x: -x["score"])
    return scored[:top_k]
