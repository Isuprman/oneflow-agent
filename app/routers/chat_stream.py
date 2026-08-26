# OneFlow 聊天接口 — SSE 真流式：工具步骤 + 最终回复逐 token 实时推送
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..agent.engine import run_agent
from ..db import get_db
from ..deps import get_current_user
from ..learn.hook import is_learn_message, pending_intents, try_handle
from ..learn.shadow import CONFIRM_PREFIX, confirm_scene, note_and_maybe_propose
from ..models import Conversation, Scene, User
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


def _sse_from_event(event: dict) -> str:
    """把 run_agent 的过程事件转成 SSE 文本，供流式接口统一推送。

    普通对话与情境剧本执行共用：工具步骤（calling/done）、增量正文、
    错误、待确认，全部映射到前端已约定的 _sse 结构。
    """
    kind = event["type"]
    if kind == "tool_call":
        return _sse("step", {"tool": event["tool"], "status": "calling"})
    if kind == "tool_result":
        return _sse("step", {
            "tool": event["tool"],
            "status": "done",
            "success": event["success"],
            "result": _preview(event["result"]),
        })
    if kind == "delta":
        return _sse("delta", {"text": event["text"]})
    if kind == "error":
        return _sse("error", {"message": event["message"]})
    if kind == "confirm":
        return _sse("confirm", {"tool": event["tool"], "summary": event["summary"]})
    return ""


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not llm_configured(db, user.id):
        raise HTTPException(status_code=400, detail="未配置 LLM：请先在「设置」页填写你的 LLM 密钥")

    # ── 情境剧本钩子：消息以「场景 」开头时，查该用户启用的同名剧本 ──
    #    命中则下面的 event_gen 走逐条执行分支；未命中保持 None，原样交给 agent。
    scene = None
    if body.message.startswith("场景 "):
        scene_name = body.message[len("场景 "):].strip()
        if scene_name:
            scene = (
                db.query(Scene)
                .filter(Scene.user_id == user.id, Scene.name == scene_name, Scene.enabled == 1)
                .first()
            )

    conv_id = body.conversation_id
    if conv_id is not None:
        conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
        if conv is None or conv.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
    else:
        conv = Conversation(
            user_id=user.id,
            title=f"场景 · {scene.name}" if scene is not None else body.message[:20],
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)
        conv_id = conv.id

    # ── 影子模式：fire-and-forget 记录本条指令，命中阈值时发「存为剧本」提议通知 ──
    #    确认指令本身不入轨（避免混进步骤）；异常静默，不阻塞流。
    async def _shadow_note():
        try:
            if not body.message.strip().startswith(CONFIRM_PREFIX):
                note_and_maybe_propose(db, conv_id, user.id, body.message)
        except Exception:
            db.rollback()

    asyncio.create_task(_shadow_note())

    async def event_gen():
        queue: asyncio.Queue = asyncio.Queue()

        # ── 情境剧本执行：命中「场景 xxx」→ 逐条喂给 agent 并把每步结果拼成回复流式推送 ──
        #    放在自学习钩子之前：消息以「场景 」开头时意图明确，先接管；
        #    单步异常只记为失败，不中断整场。无命中（scene=None）走下方普通/自学习流程。
        if scene is not None:
            scene_steps = [s.strip() for s in (scene.steps or "").splitlines() if s.strip()]
            replies: list[str] = []
            for idx, step in enumerate(scene_steps, start=1):
                if idx > 1:
                    yield _sse("delta", {"text": "\n\n"})
                q: asyncio.Queue = asyncio.Queue()

                async def scene_on_event(event: dict, _q: asyncio.Queue = q) -> None:
                    await _q.put(_sse_from_event(event))

                task = asyncio.create_task(
                    run_agent(db, user, conv_id, step, on_event=scene_on_event, stream=True)
                )
                try:
                    while True:
                        if task.done():
                            while not q.empty():
                                yield q.get_nowait()
                            break
                        try:
                            yield await asyncio.wait_for(q.get(), timeout=0.2)
                        except asyncio.TimeoutError:
                            continue
                    reply, _agent_steps, _trace = task.result()
                except Exception as e:  # 单步兜底：标记失败，继续跑后续步骤
                    reply = f"[步骤 {idx} 执行失败] {e}"
                replies.append(reply)
            yield _sse("done", {
                "conversation_id": conv_id,
                "reply": "\n\n".join(replies),
                "steps": len(scene_steps),
                "trace": [],
            })
            return

        # ── 自学习钩子：学习请求 / 审批指令 / 待确认跟进 不走 agent ──
        if is_learn_message(body.message) or user.id in pending_intents:
            yield _sse("step", {"tool": "self_learn", "status": "calling"})

            def on_progress(stage: str) -> None:
                queue.put_nowait(_sse("step", {"tool": "self_learn", "status": "running", "message": stage}))

            hook_task = asyncio.create_task(
                try_handle(db, user, conv_id, body.message, on_progress=on_progress)
            )
            while True:
                if hook_task.done():
                    while not queue.empty():
                        yield queue.get_nowait()
                    break
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
            learn_reply = hook_task.result()
            if learn_reply is not None:
                yield _sse("step", {"tool": "self_learn", "status": "done", "success": True})
                yield _sse("done", {
                    "conversation_id": conv_id,
                    "reply": learn_reply,
                    "steps": 0,
                    "trace": [],
                })
                return

        # ── 影子模式确认钩子：「存为剧本」→ 把本会话流程落成情境剧本（agent 之前接管）──
        if body.message.strip().startswith(CONFIRM_PREFIX):
            shadow_reply = confirm_scene(db, user, conv_id)
            yield _sse("done", {
                "conversation_id": conv_id,
                "reply": shadow_reply,
                "steps": 0,
                "trace": [],
            })
            return

        async def on_event(event: dict) -> None:
            await queue.put(_sse_from_event(event))

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
