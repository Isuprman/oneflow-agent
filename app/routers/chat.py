# OneFlow 聊天接口 — Agent 引擎入口
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..agent.engine import run_agent
from ..db import get_db
from ..deps import get_current_user
from ..learn.hook import try_handle
from ..models import Conversation, User
from ..schemas import ChatRequest, ChatResponse
from ..user_cfg import llm_configured

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not llm_configured(db, user.id):
        raise HTTPException(status_code=400, detail="未配置 LLM：请先在「设置」页填写你的 LLM 密钥")

    conv_id = body.conversation_id
    if conv_id is not None:
        conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
        if conv is None or conv.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
    else:
        conv = Conversation(user_id=user.id, title=body.message[:20])
        db.add(conv)
        db.commit()
        db.refresh(conv)
        conv_id = conv.id

    # 自学习钩子：学习请求/审批指令不走 agent
    learn_reply = await try_handle(db, user, conv_id, body.message)
    if learn_reply is not None:
        return ChatResponse(conversation_id=conv_id, reply=learn_reply, steps=0, trace=[])

    reply, steps, trace = await run_agent(db, user, conv_id, body.message)
    return ChatResponse(conversation_id=conv_id, reply=reply, steps=steps, trace=trace)
