# MCP server 配置管理路由 — 增删改查 + 刷新重连
#
# 服务为全局共享（McpServer.user_id 置空），任何登录用户可管理；
# 写操作即时生效：启用即连接并注册工具，停用/删除即下线注销。
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..mcp_client import (
    _parse_env,
    connection_status,
    register_server,
    registered_tools,
    unregister_server,
    validate_command,
)
from ..models import McpServer, User

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


class McpServerIn(BaseModel):
    name: str
    command: Optional[str] = ""     # stdio 启动命令（与 url 二选一）
    url: Optional[str] = ""         # streamable HTTP 端点（与 command 二选一）
    env_json: Optional[str] = "{}"  # JSON 对象：传给子进程的环境变量（API key 类）
    enabled: bool = True


class McpServerUpdate(BaseModel):
    command: Optional[str] = None
    url: Optional[str] = None
    env_json: Optional[str] = None
    enabled: Optional[bool] = None


class McpServerOut(BaseModel):
    id: int
    name: str
    command: str
    url: str
    env_json: str
    enabled: bool
    status: str                  # connected / error / off
    tools: list[str]             # 已注册工具名（mcp_<server>_<tool>）
    created_at: Optional[str] = None


def _to_out(row: McpServer) -> McpServerOut:
    return McpServerOut(
        id=row.id,
        name=row.name,
        command=row.command or "",
        url=row.url or "",
        env_json=row.env_json or "{}",
        enabled=bool(row.enabled),
        status=connection_status(row.name),
        tools=registered_tools(row.name),
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


def _validate_payload(command: str, url: str, env_json: str) -> None:
    """新建/更新共用的合法性检查，不通过直接 400。"""
    cmd, link = (command or "").strip(), (url or "").strip()
    if not cmd and not link:
        raise HTTPException(status_code=400, detail="command 与 url 至少填一个")
    if cmd and link:
        raise HTTPException(status_code=400, detail="command 与 url 只能填一个")
    if err := validate_command(cmd):
        raise HTTPException(status_code=400, detail=err)
    try:
        env = json.loads(env_json or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="env_json 不是合法 JSON")
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise HTTPException(status_code=400, detail="env_json 需为字符串到字符串的对象")


@router.get("", response_model=list[McpServerOut])
def list_servers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(McpServer).order_by(McpServer.id.asc()).all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=McpServerOut, status_code=201)
def add_server(
    body: McpServerIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 不能为空")
    if len(name) > 64:
        raise HTTPException(status_code=400, detail="name 过长（≤64 字符）")
    if " " in name or "/" in name:
        raise HTTPException(status_code=400, detail="name 不能含空格或斜杠（用于工具命名空间）")
    if db.query(McpServer).filter(McpServer.name == name).first() is not None:
        raise HTTPException(status_code=409, detail=f"服务 {name} 已存在")

    command, url = (body.command or "").strip(), (body.url or "").strip()
    _validate_payload(command, url, body.env_json)

    row = McpServer(
        # 全局共享：user_id 置空；列保留供未来按用户隔离
        user_id=None,
        name=name,
        command=command,
        url=url,
        env_json=body.env_json or "{}",
        enabled=1 if body.enabled else 0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    if row.enabled:
        outcome = register_server(name, command, url, _parse_env(row.env_json))
        if not outcome["ok"]:
            # 配置已保存但连接失败：行保留（enabled），前端以 error 状态展示并可刷新重试
            pass
    return _to_out(row)


def _get_row(db: Session, server_id: int) -> McpServer:
    row = db.query(McpServer).filter(McpServer.id == server_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="MCP 服务不存在")
    return row


@router.put("/{server_id}", response_model=McpServerOut)
def update_server(
    server_id: int,
    body: McpServerUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = _get_row(db, server_id)

    new_command = (body.command if body.command is not None else row.command or "").strip()
    new_url = (body.url if body.url is not None else row.url or "").strip()
    new_env = body.env_json if body.env_json is not None else row.env_json or "{}"
    _validate_payload(new_command, new_url, new_env)

    row.command, row.url, row.env_json = new_command, new_url, new_env
    if body.enabled is not None:
        row.enabled = 1 if body.enabled else 0
    db.commit()
    db.refresh(row)

    # 即时生效：停用即下线；启用/改配置即重建连接
    if row.enabled:
        outcome = register_server(row.name, row.command, row.url, _parse_env(row.env_json))
        if not outcome["ok"]:
            pass  # 连接失败不回滚配置，状态接口会显示 error
    else:
        unregister_server(row.name)
    return _to_out(row)


@router.delete("/{server_id}", status_code=204)
def delete_server(
    server_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = _get_row(db, server_id)
    unregister_server(row.name)
    db.delete(row)
    db.commit()


@router.post("/{name}/refresh", response_model=McpServerOut)
def refresh_server(
    name: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重连指定服务并列出其工具（断线恢复 / 工具清单更新的手动入口）。"""
    row = db.query(McpServer).filter(McpServer.name == name).first()
    if row is None:
        raise HTTPException(status_code=404, detail="MCP 服务不存在")
    if not row.enabled:
        raise HTTPException(status_code=400, detail="服务已停用，请先开启再刷新")
    outcome = register_server(row.name, row.command, row.url, _parse_env(row.env_json))
    if not outcome["ok"]:
        raise HTTPException(status_code=502, detail=outcome["error"] or f"MCP 服务 {name} 重连失败")
    db.refresh(row)
    return _to_out(row)
