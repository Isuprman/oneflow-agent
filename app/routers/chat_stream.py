# OneFlow 聊天接口 — SSE 真流式：工具步骤 + 最终回复逐 token 实时推送
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..agent.engine import run_agent
from ..db import get_db
from ..deps import get_current_user
from ..models import Conversation, User
from ..schemas import ChatRequest
from ..user_cfg import llm_configured

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 工具结果推给前端展示时的长度上限（完整结果仍落库供 /trace 读取）
RESULT_PREVIEW_LIMIT = 300


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _preview(value) -> object:
    """工具结果预览：超长 JSON 文本截断，避免大结果刷屏。"""
    text = json.dumps(value, ensure_ascii=False)
    if len(text) <= RESULT_PREVIEW_LIMIT:
        return value
    return text[:RESULT_PREVIEW_LIMIT] + "…（完整结果见工具轨迹）"


@router.post("/stream")
async def chat_stream(
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

    async def event_gen():
        queue: asyncio.Queue = asyncio.Queue()

        async def on_event(event: dict) -> None:
            kind = event["type"]
            if kind == "tool_call":
                await queue.put(_sse("step", {"tool": event["tool"], "status": "calling"}))
            elif kind == "tool_result":
                await queue.put(_sse("step", {
                    "tool": event["tool"],
                    "status": "done",
                    "success": event["success"],
                    "result": _preview(event["result"]),
                }))
            elif kind == "delta":
                await queue.put(_sse("delta", {"text": event["text"]}))
            elif kind == "error":
                await queue.put(_sse("error", {"message": event["message"]}))
            elif kind == "confirm":
                await queue.put(_sse("confirm", {"tool": event["tool"], "summary": event["summary"]}))

        task = asyncio.create_task(
            run_agent(db, user, conv_id, body.message, on_event=on_event, stream=True)
        )
        try:
            while True:
                if task.done():
                    # 收尾：排空残余事件后退出
                    while not queue.empty():
                        yield queue.get_nowait()
                    break
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
            reply, steps, trace = task.result()  # run_agent 内部兜底，不会抛
        except Exception as e:  # 防御性兜底：任何意外都以 error 事件告知前端
            yield _sse("error", {"message": f"服务异常: {e}"})
            reply, steps, trace = "", 0, []
        # 结束事件：带完整 reply + steps + trace 供前端校正/展示轨迹
        yield _sse("done", {
            "conversation_id": conv_id,
            "reply": reply,
            "steps": steps,
            "trace": trace,
        })

    return StreamingResponse(event_gen(), media_type="text/event-stream")
