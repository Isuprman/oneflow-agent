# OneFlow 云端 Embedding —— 记忆语义召回用
# 策略：走用户 LLM 厂商的 embedding 端点（零本地负担）；任何失败静默返回 None，
# 调用方自动降级为全量注入，保证功能不因 embedding 不可用而中断。
import asyncio
import json
import math
from typing import Optional

from ..config import settings

# 各 provider → embedding 模型（未收录/调用失败则降级）
EMBED_MODEL_BY_PROVIDER = {
    "openai": "text-embedding-3-small",
    "qwen": "text-embedding-v3",
    "deepseek": "",  # DeepSeek 暂无 embedding 端点：直接降级
    "anthropic": "",  # Anthropic 同理
}


def build_embed_model(provider: str) -> str:
    return EMBED_MODEL_BY_PROVIDER.get(provider, "")


async def embed_text(text: str, cfg: dict | None) -> Optional[list[float]]:
    """把文本转成向量；失败（不支持/无key/网络）一律返回 None。"""
    if not text or not text.strip():
        return None
    provider = (cfg.get("provider") if cfg else None) or settings.llm_provider
    model = build_embed_model(provider)
    if not model:
        return None
    api_key = (cfg.get("api_key") if cfg else None) or settings.llm_api_key
    if not api_key:
        return None

    import litellm

    kwargs = {"model": f"{provider}/{model}", "input": text[:800], "api_key": api_key}
    base_url = (cfg.get("base_url") if cfg else None) or settings.llm_base_url
    # embedding 端点用 chat base_url 通常兼容（OpenAI 兼容模式）
    if base_url:
        kwargs["api_base"] = base_url
    try:
        resp = await asyncio.wait_for(litellm.aembedding(**kwargs), timeout=15)
        vector = resp.data[0]["embedding"]
        return [float(x) for x in vector]
    except Exception:
        return None


def embedding_to_json(vector: Optional[list[float]]) -> Optional[str]:
    if vector is None:
        return None
    return json.dumps(vector)


def json_to_embedding(raw: Optional[str]) -> Optional[list[float]]:
    if not raw:
        return None
    try:
        value = json.loads(raw)
        if isinstance(value, list) and value:
            return [float(x) for x in value]
    except (ValueError, TypeError):
        pass
    return None


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
