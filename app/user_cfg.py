# OneFlow 每用户配置读写助手
# key 用点分字符串：LLM 用 llm.provider / llm.model / llm.api_key / llm.base_url，
# 酒店用 hotel.base_url / hotel.api_key。用户配置覆盖全局默认（.env）。
from .config import provider_default, settings
from .models import UserSetting

_LLM_KEYS = ("llm.provider", "llm.model", "llm.api_key", "llm.base_url")
_HOTEL_KEYS = ("hotel.base_url", "hotel.api_key")


def _load_map(db, user_id, keys) -> dict:
    """按 user_id 查这些 key，返回 {key: value}（未设置的 key 不出现）。"""
    rows = (
        db.query(UserSetting)
        .filter(UserSetting.user_id == user_id, UserSetting.key.in_(keys))
        .all()
    )
    return {row.key: row.value for row in rows}


def _set_all(db, user_id, mapping: dict) -> None:
    """对 mapping 里每一项 upsert；已存在则更新 value；commit。"""
    rows = (
        db.query(UserSetting)
        .filter(UserSetting.user_id == user_id, UserSetting.key.in_(list(mapping)))
        .all()
    )
    by_key = {row.key: row for row in rows}
    for key, value in mapping.items():
        row = by_key.get(key)
        if row is None:
            db.add(UserSetting(user_id=user_id, key=key, value=value))
        else:
            row.value = value
    db.commit()


def get_llm_map(db, user_id) -> dict:
    """用户已保存的 LLM 配置（未设的 key 不出现）。"""
    return _load_map(db, user_id, _LLM_KEYS)


def save_llm(db, user_id, provider, model, api_key, base_url) -> None:
    _set_all(
        db,
        user_id,
        {
            "llm.provider": provider,
            "llm.model": model,
            "llm.api_key": api_key,
            "llm.base_url": base_url,
        },
    )


def get_llm_cfg(db, user_id) -> dict:
    """用户配置覆盖全局默认；返回 {"provider", "model", "api_key", "base_url"}。

    解析顺序：每用户已存设置 → provider 内置默认（PROVIDER_DEFAULTS）→ 全局默认（.env）。
    """
    m = get_llm_map(db, user_id)
    provider = m.get("llm.provider") or settings.llm_provider
    return {
        "provider": provider,
        "model": m.get("llm.model") or provider_default(provider, "model") or settings.llm_model,
        "api_key": m.get("llm.api_key") or settings.llm_api_key,
        "base_url": provider_default(provider, "base_url") or settings.llm_base_url,
    }


def get_hotel_cfg(db, user_id) -> dict:
    """用户 hotel 配置覆盖全局；返回 {"base_url", "api_key"}。"""
    m = _load_map(db, user_id, _HOTEL_KEYS)
    return {
        "base_url": m.get("hotel.base_url") or settings.hotel_base_url,
        "api_key": m.get("hotel.api_key") or settings.hotel_api_key,
    }


def save_hotel(db, user_id, base_url, api_key) -> None:
    _set_all(db, user_id, {"hotel.base_url": base_url, "hotel.api_key": api_key})


def llm_configured(db, user_id) -> bool:
    """用户或全局任一 api_key 非空。"""
    m = get_llm_map(db, user_id)
    return bool(m.get("llm.api_key") or settings.llm_api_key)
