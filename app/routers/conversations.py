# OneFlow 会话路由
import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Conversation, Message, ToolCallLog, User
from ..schemas import ConversationCreate, ConversationOut, MessageOut, ToolStep

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _to_out(conv: Conversation) -> ConversationOut:
    return ConversationOut(id=conv.id, title=conv.title, created_at=conv.created_at.isoformat())


def _get_owned_conversation(conversation_id: int, current_user: User, db: Session) -> Conversation:
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == current_user.id)
        .first()
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conv


@router.post("", response_model=ConversationOut)
def create_conversation(
    body: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = Conversation(user_id=current_user.id, title=body.title)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return _to_out(conv)


@router.get("", response_model=List[ConversationOut])
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    convs = (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
        .order_by(Conversation.id.desc())
        .all()
    )
    return [_to_out(c) for c in convs]


@router.get("/{conversation_id}/messages", response_model=List[MessageOut])
def list_messages(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_conversation(conversation_id, current_user, db)
    return (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.id.asc())
        .all()
    )


@router.get("/{conversation_id}/trace", response_model=List[ToolStep])
def conversation_trace(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_owned_conversation(conversation_id, current_user, db)
    logs = (
        db.query(ToolCallLog)
        .filter(ToolCallLog.conversation_id == conversation_id)
        .order_by(ToolCallLog.id.asc())
        .all()
    )
    steps = []
    for log in logs:
        arguments = _parse_json(log.arguments)
        result = _parse_json(log.result)
        steps.append(
            ToolStep(
                tool=log.tool_name,
                arguments=arguments,
                result=result,
                success=bool(log.success),
            )
        )
    return steps


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = _get_owned_conversation(conversation_id, current_user, db)
    db.delete(conv)
    db.commit()


def _parse_json(text) -> dict:
    if not text:
        return {}
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return {}
