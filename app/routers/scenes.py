# OneFlow 情境剧本路由 — 预置指令集，聊天里「场景 xxx」或设置页「立即执行」一键顺序跑
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..agent.engine import run_agent
from ..db import get_db
from ..deps import get_current_user
from ..models import Conversation, Scene, User

router = APIRouter(prefix="/api/scenes", tags=["scenes"])

MAX_STEPS = 10


class SceneCreate(BaseModel):
    name: str
    steps: list[str]


class SceneUpdate(BaseModel):
    enabled: Optional[bool] = None


class SceneOut(BaseModel):
    id: int
    name: str
    steps: list[str]
    step_count: int
    enabled: bool
    created_at: Optional[str] = None


class SceneStepResult(BaseModel):
    step: str
    reply: str
    success: bool


def _steps_of(scene: Scene) -> list[str]:
    """把按行存储的 steps 拆回指令数组（跳过空行）。"""
    return [s.strip() for s in (scene.steps or "").splitlines() if s.strip()]


def _to_out(scene: Scene) -> SceneOut:
    steps = _steps_of(scene)
    return SceneOut(
        id=scene.id,
        name=scene.name,
        steps=steps,
        step_count=len(steps),
        enabled=bool(scene.enabled),
        created_at=scene.created_at.isoformat() if scene.created_at else None,
    )


def _get_owned(db: Session, scene_id: int, user_id: int) -> Scene:
    scene = (
        db.query(Scene)
        .filter(Scene.id == scene_id, Scene.user_id == user_id)
        .first()
    )
    if scene is None:
        raise HTTPException(status_code=404, detail="剧本不存在")
    return scene


@router.get("", response_model=list[SceneOut])
def list_scenes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(Scene)
        .filter(Scene.user_id == user.id)
        .order_by(Scene.id.asc())
        .all()
    )
    return [_to_out(r) for r in rows]


@router.post("", response_model=SceneOut)
def create_scene(
    body: SceneCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="剧本名不能为空")
    if len(name) > 64:
        raise HTTPException(status_code=400, detail="剧本名最长 64 字")
    steps = [s.strip() for s in body.steps if s.strip()]
    if not steps:
        raise HTTPException(status_code=400, detail="至少需要一条指令")
    if len(steps) > MAX_STEPS:
        raise HTTPException(status_code=400, detail=f"指令最多 {MAX_STEPS} 条")
    if (
        db.query(Scene)
        .filter(Scene.user_id == user.id, Scene.name == name)
        .first()
        is not None
    ):
        raise HTTPException(status_code=409, detail="同名剧本已存在")
    scene = Scene(user_id=user.id, name=name, steps="\n".join(steps), enabled=1)
    db.add(scene)
    try:
        db.commit()
    except IntegrityError:  # 并发下唯一约束兜底
        db.rollback()
        raise HTTPException(status_code=409, detail="同名剧本已存在")
    db.refresh(scene)
    return _to_out(scene)


@router.put("/{scene_id}", response_model=SceneOut)
def update_scene(
    scene_id: int,
    body: SceneUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scene = _get_owned(db, scene_id, user.id)
    if body.enabled is True:
        scene.enabled = 1
    elif body.enabled is False:
        scene.enabled = 0
    db.commit()
    db.refresh(scene)
    return _to_out(scene)


@router.delete("/{scene_id}", status_code=204)
def delete_scene(
    scene_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scene = _get_owned(db, scene_id, user.id)
    db.delete(scene)
    db.commit()


@router.post("/{scene_id}/run", response_model=list[SceneStepResult])
async def run_scene(
    scene_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """同步顺序执行剧本：每条指令喂给 run_agent，单步失败不中断后续。

    自动新建一个「场景 · 名字」会话承载全程上下文，返回每步的
    {step, reply, success} 数组（前端据此弹完成步数）。
    """
    scene = _get_owned(db, scene_id, user.id)
    if not scene.enabled:
        raise HTTPException(status_code=400, detail="剧本未启用")
    steps = _steps_of(scene)
    if not steps:
        raise HTTPException(status_code=400, detail="剧本没有可执行的指令")

    conv = Conversation(user_id=user.id, title=f"场景 · {scene.name}")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    results: list[SceneStepResult] = []
    for step in steps:
        try:
            reply, _agent_steps, _trace = await run_agent(db, user, conv.id, step)
            results.append(SceneStepResult(step=step, reply=reply, success=True))
        except Exception as e:  # 单步兜底：标记失败，继续跑后续步骤
            results.append(SceneStepResult(step=step, reply=f"执行失败：{e}", success=False))
    return results
