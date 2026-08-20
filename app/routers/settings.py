# OneFlow 每用户配置接口
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas import HotelConfigIn, HotelConfigOut, LlmConfigIn, LlmConfigOut
from ..user_cfg import (
    _HOTEL_KEYS,
    _load_map,
    get_hotel_cfg,
    get_llm_cfg,
    get_llm_map,
    llm_configured,
    save_hotel,
    save_llm,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/llm", response_model=LlmConfigOut)
def get_llm_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cfg = get_llm_cfg(db, current_user.id)
    saved = get_llm_map(db, current_user.id)
    return LlmConfigOut(
        provider=cfg["provider"],
        model=cfg["model"],
        api_key_set=bool(saved.get("llm.api_key")),
        base_url=cfg["base_url"],
        configured=llm_configured(db, current_user.id),
    )


@router.put("/llm", response_model=LlmConfigOut)
def put_llm_settings(
    body: LlmConfigIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    provider = body.provider.strip()
    model = body.model.strip()
    if not provider or not model:
        raise HTTPException(status_code=400, detail="provider 与 model 不能为空")
    save_llm(db, current_user.id, provider, model, body.api_key, body.base_url)
    cfg = get_llm_cfg(db, current_user.id)
    saved = get_llm_map(db, current_user.id)
    return LlmConfigOut(
        provider=cfg["provider"],
        model=cfg["model"],
        api_key_set=bool(body.api_key or saved.get("llm.api_key")),
        base_url=cfg["base_url"],
        configured=llm_configured(db, current_user.id),
    )


@router.get("/hotel", response_model=HotelConfigOut)
def get_hotel_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cfg = get_hotel_cfg(db, current_user.id)
    saved = _load_map(db, current_user.id, _HOTEL_KEYS)
    return HotelConfigOut(
        base_url=cfg["base_url"],
        api_key_set=bool(saved.get("hotel.api_key")),
        configured=bool(cfg["base_url"] or cfg["api_key"]),
    )


@router.put("/hotel", response_model=HotelConfigOut)
def put_hotel_settings(
    body: HotelConfigIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    save_hotel(db, current_user.id, body.base_url, body.api_key)
    cfg = get_hotel_cfg(db, current_user.id)
    saved = _load_map(db, current_user.id, _HOTEL_KEYS)
    return HotelConfigOut(
        base_url=cfg["base_url"],
        api_key_set=bool(body.api_key or saved.get("hotel.api_key")),
        configured=bool(cfg["base_url"] or cfg["api_key"]),
    )
