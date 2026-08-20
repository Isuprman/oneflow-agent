# OneFlow 配置 — pydantic-settings 从 .env 读取
# LLM 厂商由用户自选：LLM_PROVIDER + LLM_MODEL + LLM_API_KEY
import os
from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent

# LLM provider → 内置默认配置（模型无关分录，只存 base_url / 默认模型）。
# 解析顺序：每用户已存设置 → provider 内置默认 → 全局默认（.env）。
PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {"model": "gpt-5.6-sol", "base_url": ""},
    "anthropic": {"model": "claude-opus-5", "base_url": ""},
    "deepseek": {
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
    },
    "qwen": {"model": "qwen3.8-max", "base_url": ""},
}


def provider_default(provider: str, field: str) -> str:
    """取某 provider 的内置默认字段值；未收录的 provider 返回空串。"""
    return PROVIDER_DEFAULTS.get(provider, {}).get(field, "")


class Settings(BaseSettings):
    llm_provider: str = "openai"
    llm_model: str = "gpt-5.6-sol"
    llm_api_key: str = ""
    llm_base_url: str = ""

    hotel_base_url: str = ""
    hotel_api_key: str = ""

    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 60 * 24 * 7

    max_steps: int = 15
    # 历史上下文预算（字符数，中文约 1 字/token）：超预算从最旧消息开始裁剪
    context_budget_chars: int = 48000
    db_path: str = str(BASE_DIR / "oneflow.db")

    model_config = {"env_file": str(BASE_DIR / ".env"), "env_file_encoding": "utf-8"}


settings = Settings()
