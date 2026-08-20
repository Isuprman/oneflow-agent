# OneFlow Agent 循环（核心）：LLM 判断 -> 工具调用 -> 循环直到给出文本回复
import asyncio
import json

from ..config import settings
from ..db import SessionLocal  # noqa: F401  保持与规范一致的依赖导入
from ..models import Message, ToolCallLog, UserMemory
from ..tools.registry import execute, schemas
from . import llm as llm_mod
from .context import trim_history
from .prompts import SYSTEM_PROMPT


async def _emit(on_event, event: dict) -> None:
    """向调用方（如 SSE 路由）推送过程事件，兼容同步/异步回调。"""
    if on_event is None:
        return
    result = on_event(event)
    if asyncio.iscoroutine(result):
        await result


async def run_agent(
    db,
    user,
    conversation_id: int,
    user_msg: str,
    on_event=None,
    stream: bool = False,
) -> tuple[str, int, list[dict]]:
    """执行一个 agent 回合。

    返回 (reply_text, steps, trace)，trace 为 list[dict]，
    每项 {"tool": name, "arguments": dict, "result": dict, "success": bool}。

    on_event：过程事件回调（tool_call/tool_result/delta/error），供 SSE 真流式透传。
    stream：为 True 时最终回复逐 token 以 delta 事件实时推出。
    """
    # 1. 先在 DB 加一条 user 消息
    db.add(Message(conversation_id=conversation_id, role="user", content=user_msg))
    db.commit()

    # 加载每用户 LLM 配置（覆盖全局默认）
    from ..user_cfg import get_llm_cfg

    cfg = get_llm_cfg(db, user.id)

    # 2. 构造跨轮基线上下文：读取该会话已有的 user/assistant 文本消息（排除 tool）
    rows = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation_id,
            Message.role.in_(["user", "assistant"]),
            Message.content.isnot(None),
        )
        .order_by(Message.id.asc())
        .all()
    )
    history = []
    for r in rows:
        item = {"role": r.role, "content": r.content or ""}
        # 思考模型（deepseek-reasoner 等）要求多轮原样回传思维链，缺了会 400
        if r.role == "assistant" and r.reasoning_content:
            item["reasoning_content"] = r.reasoning_content
        history.append(item)

    # 2.5 历史超预算时从最旧开始裁剪，防长会话撑爆窗口
    history = trim_history(history)

    # 3. 尾部追加当前用户消息（若 history 最后一条就是它则去重）
    if not history or not (
        history[-1]["role"] == "user" and history[-1]["content"] == user_msg
    ):
        history.append({"role": "user", "content": user_msg})

    messages = history
    tools = schemas()

    # 3.5. 加载长期记忆（最近 20 条），注入 system 供 LLM 参考
    mem_rows = (
        db.query(UserMemory)
        .filter(UserMemory.user_id == user.id)
        .order_by(UserMemory.updated_at.desc())
        .limit(20)
        .all()
    )
    system_text = SYSTEM_PROMPT
    if mem_rows:
        system_text += "\n\n【关于用户的长期记忆】\n" + "\n".join(
            f"- {m.content}" for m in mem_rows
        )

    trace = []
    steps = 0
    call_id = 0

    while True:
        steps += 1
        if steps > settings.max_steps:
            text = f"任务步骤过多（{settings.max_steps}步），已终止，请拆细一点。"
            db.add(Message(conversation_id=conversation_id, role="assistant", content=text))
            db.commit()
            return text, steps, trace

        payload = [{"role": "system", "content": system_text}] + messages
        # 真流式：最终回复的正文增量经 delta 事件实时推出（工具调用轮无正文）
        on_delta = (
            (lambda piece: _emit(on_event, {"type": "delta", "text": piece}))
            if (stream and on_event is not None)
            else None
        )
        res = await llm_mod.chat(payload, tools, cfg, on_delta=on_delta)

        # 调用失败：推送错误事件并直接返回，错误文本不落库（避免污染后续历史）
        if res.error:
            await _emit(on_event, {"type": "error", "message": res.text})
            return res.text, steps, trace

        if res.tool_call is not None:
            tc = res.tool_call
            await _emit(
                on_event,
                {"type": "tool_call", "tool": tc.name, "arguments": tc.arguments},
            )
            if tc.name == "delegate":
                agent_name = tc.arguments.get("agent_name")
                instruction = tc.arguments.get("instruction")
                from .subagent import run_subagent, SUB_AGENTS

                if agent_name not in SUB_AGENTS:
                    result = {"success": False, "error": f"未知子智能体: {agent_name}，可选 life/finance/travel"}
                else:
                    try:
                        sub_text, sub_steps = await run_subagent(
                            db, user, agent_name, instruction, cfg
                        )
                        result = {
                            "success": True,
                            "agent": agent_name,
                            "text": sub_text,
                            "steps": sub_steps,
                        }
                    except Exception as e:
                        result = {"success": False, "error": f"子智能体执行失败: {e}"}
            else:
                result = execute(tc.name, tc.arguments, user, db)
            success = result.get("success", False)
            trace.append(
                {
                    "tool": tc.name,
                    "arguments": tc.arguments,
                    "result": result,
                    "success": success,
                }
            )
            await _emit(
                on_event,
                {"type": "tool_result", "tool": tc.name, "success": success, "result": result},
            )

            fallback = tc.name
            tool_call_id = f"call_{call_id}"
            call_id += 1

            assistant_msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                ],
            }
            # 思考模型要求每条 assistant 消息带回思维链，同循环内也不能丢
            if res.reasoning_content:
                assistant_msg["reasoning_content"] = res.reasoning_content
            messages.append(assistant_msg)
            # 工具结果（含失败时的错误提示）回填给 LLM，让其修正参数或换方案重试
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

            db.add(
                ToolCallLog(
                    conversation_id=conversation_id,
                    tool_name=tc.name,
                    arguments=json.dumps(tc.arguments, ensure_ascii=False),
                    result=json.dumps(result, ensure_ascii=False),
                    success=1 if success else 0,
                )
            )
            # assistant(tool_call) 与 tool 结果消息也落库，供 /trace 与审计读取
            db.add(
                Message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=None,
                    tool_call=json.dumps(
                        {"name": tc.name, "arguments": tc.arguments},
                        ensure_ascii=False,
                    ),
                )
            )
            db.add(
                Message(
                    conversation_id=conversation_id,
                    role="tool",
                    content=json.dumps(result, ensure_ascii=False),
                )
            )
            db.commit()
            continue

        # 有文本：落库并返回（思维链一并落库，供下一轮历史回传）
        db.add(
            Message(
                conversation_id=conversation_id,
                role="assistant",
                content=res.text,
                reasoning_content=res.reasoning_content,
            )
        )
        db.commit()
        return res.text, steps, trace
