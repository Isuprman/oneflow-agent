# Embedding 工具测试 — 纯函数与降级策略（不发真实请求）
import asyncio

from app.agent.embed import (
    build_embed_model,
    cosine,
    embed_text,
    embedding_to_json,
    json_to_embedding,
)


def test_embed_model_mapping_and_degrade():
    assert build_embed_model("openai") == "text-embedding-3-small"
    assert build_embed_model("qwen") == "text-embedding-v3"
    # 无 embedding 端点的厂商直接降级
    assert build_embed_model("deepseek") == ""
    assert build_embed_model("anthropic") == ""


def test_embed_text_returns_none_without_support():
    # deepseek 无 embedding 端点：不发请求直接 None
    result = asyncio.run(embed_text("你好", {"provider": "deepseek", "api_key": "x"}))
    assert result is None
    # 无 key 也直接 None
    result = asyncio.run(embed_text("你好", {"provider": "openai", "api_key": ""}))
    assert result is None


def test_json_roundtrip():
    vector = [0.1, -0.2, 0.3]
    raw = embedding_to_json(vector)
    assert json_to_embedding(raw) == vector
    assert json_to_embedding(None) is None
    assert json_to_embedding("not-json") is None
    assert json_to_embedding("[]") is None


def test_cosine():
    assert abs(cosine([1, 0], [1, 0]) - 1.0) < 1e-9
    assert abs(cosine([1, 0], [0, 1])) < 1e-9
    assert cosine([], [1]) == 0.0
    assert cosine([1, 2], [1, 2, 3]) == 0.0  # 维度不一致视为不可比
