# OneFlow Agent 循环（核心）：LLM 判断 -> 工具调用 -> 循环直到给出文本回复。
# 记忆召回在 memory_recall.py，确认/信任在 confirm.py，委派执行在 subagent.py。
import asyncio
import json

from ..config import settings
from ..db import SessionLocal  # noqa: F401  保持与规范一致的依赖导入
from ..learn.hook import get_trust_level
from ..models import Message, PendingAction, ToolCallLog
from ..tools.registry import execute, schemas
from . import llm as llm_mod
from .confirm import _is_cancel, _is_confirm, _needs_confirm, _pending_summary
from .context import trim_history
from .memory_recall import _recall_memories  # noqa: F401  兼容导出（测试从本模块导入）
from .prompts import SYSTEM_PROMPT
from .subagent import execute_delegate


async def _emit(on_event, event: dict) -> None:
    """向调用方（如 SSE 路由）推送过程事件，兼容同步/异步回调。"""
    if on_event is None:
        return
    result = on_event(event)
    if asyncio.iscoroutine(result):
        await result


def _tool_schemas(db, user_id: int) -> list:
    """工具 schema：delegate 的 agent_name 动态列出内置+用户自定义子智能体。"""
    from ..tools.custom_agent import available_agent_names

    result = schemas()
    try:
        names = available_agent_names(db, user_id)
    except Exception:
        names = None
    if names:
        for s in result:
            fn = s.get("function", {})
            if fn.get("name") == "delegate":
                fn["parameters"]["properties"]["agent_name"]["description"] = (
                    "可选：" + " | ".join(names)
                )
    return result


async def run_agent(
    db,
    user,
    conversation_id: int,
    user_msg: str,
    on_event=None,
    stream: bool = False,
    bypass_away: bool = False,
) -> tuple[str, int, list[dict]]:
    """执行一个 agent 回合。

    返回 (reply_text, steps, trace)，trace 为 list[dict]，
    每项 {"tool": name, "arguments": dict, "result": dict, "success": bool}。

    on_event：过程事件回调（tool_call/tool_result/delta/error），供 SSE 真流式透传。
    stream：为 True 时最终回复逐 token 以 delta 事件实时推出。
    bypass_away：为 True 时跳过数字分身指令接管（分身执行规则时用，避免规则文本被再次当成规则录入）。
    """
    # 1. 先在 DB 加一条 user 消息
    db.add(Message(conversation_id=conversation_id, role="user", content=user_msg))
    db.commit()

    # 加载每用户 LLM 配置（覆盖全局默认）
    from ..user_cfg import get_llm_cfg

    cfg = get_llm_cfg(db, user.id)
    # 信任旋钮：本回合内工具调用是否进确认分支（学习提案审批不受影响）
    trust_level = get_trust_level(db, user.id)

    # 1.2 数字分身：我不在 / 我回来了 / 外出期间规则录入 —— 不经 LLM，直接接管
    if not bypass_away:
        from ..learn.companion import try_handle_away_command

        away_reply = try_handle_away_command(db, user, conversation_id, user_msg)
        if away_reply is not None:
            db.add(Message(conversation_id=conversation_id, role="assistant", content=away_reply))
            db.commit()
            return away_reply, 0, []

    # 1.5 高危操作确认流程：上轮有 pending 时，本轮先处理确认/取消
    pending = (
        db.query(PendingAction)
        .filter(PendingAction.user_id == user.id, PendingAction.conversation_id == conversation_id)
        .first()
    )
    confirmed_action = None
    if pending is not None:
        if _is_confirm(user_msg):
            confirmed_action = (pending.tool_name, json.loads(pending.arguments))
            db.delete(pending)
            db.commit()
        elif _is_cancel(user_msg):
            db.delete(pending)
            db.commit()
            reply = "好的，已取消。"
            db.add(Message(conversation_id=conversation_id, role="assistant", content=reply))
            db.commit()
            return reply, 1, []
        else:
            # 既非确认也非取消：丢弃 pending，按新指令正常处理
            db.delete(pending)
            db.commit()

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
    tools = _tool_schemas(db, user.id)

    # 3.4 情绪感知：用户消息进 agent 前做轻量分类（10 分钟缓存），
    #     frustrated/tired 时收紧回复姿态（回复减半、去掉俏皮话与反问、直接给结论）
    from ..learn.companion import classify_mood, mood_system_suffix

    mood = await classify_mood(user_msg, cfg, user.id)

    # 3.5 注入画像 + 语义召回的长期记忆（无向量时自动回退最近 20 条）
    from ..tools.profile import load_profile

    system_text = SYSTEM_PROMPT
    system_text += mood_system_suffix(mood)
    profile = load_profile(db, user.id)
    if profile:
        system_text += "\n\n【用户画像】\n" + "\n".join(f"- {k}: {v}" for k, v in profile.items())
    mem_contents = await _recall_memories(db, user, user_msg, cfg)
    if mem_contents:
        system_text += "\n\n【关于用户的长期记忆】\n" + "\n".join(f"- {c}" for c in mem_contents)

    trace = []
    steps = 0
    call_id = 0

    # 3.6 上轮确认过的 pending 操作：执行并以 tool_call+结果接入上下文，让 LLM 汇报
    if confirmed_action is not None:
        name, confirmed_args = confirmed_action
        await _emit(on_event, {"type": "tool_call", "tool": name, "arguments": confirmed_args})
        result = execute(name, confirmed_args, user, db, cfg=cfg)
        success = result.get("success", False)
        trace.append({"tool": name, "arguments": confirmed_args, "result": result, "success": success})
        await _emit(on_event, {"type": "tool_result", "tool": name, "success": success, "result": result})
        tool_call_id = f"call_{call_id}"
        call_id += 1
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tool_call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(confirmed_args, ensure_ascii=False)},
                    }
                ],
            }
        )
        messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(result, ensure_ascii=False)})
        db.add(
            ToolCallLog(
                conversation_id=conversation_id,
                tool_name=name,
                arguments=json.dumps(confirmed_args, ensure_ascii=False),
                result=json.dumps(result, ensure_ascii=False),
                success=1 if success else 0,
            )
        )
        db.commit()

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
            # 信任旋钮决定是否拦截：不直接执行，暂存 pending 并向用户要确认
            if _needs_confirm(tc.name, trust_level):
                summary = _pending_summary(tc.name, tc.arguments)
                db.query(PendingAction).filter(
                    PendingAction.user_id == user.id,
                    PendingAction.conversation_id == conversation_id,
                ).delete()
                db.add(
                    PendingAction(
                        user_id=user.id,
                        conversation_id=conversation_id,
                        tool_name=tc.name,
                        arguments=json.dumps(tc.arguments, ensure_ascii=False),
                        summary=summary,
                    )
                )
                reply = f"{summary}。请回复“确认”执行，或“取消”放弃。"
                db.add(Message(conversation_id=conversation_id, role="assistant", content=reply))
                db.commit()
                await _emit(on_event, {"type": "confirm", "tool": tc.name, "summary": summary})
                return reply, steps, trace
            await _emit(
                on_event,
                {"type": "tool_call", "tool": tc.name, "arguments": tc.arguments},
            )
            if tc.name == "delegate":
                result = await execute_delegate(
                    db, user, tc.arguments.get("agent_name"), tc.arguments.get("instruction"), cfg
                )
            else:
                result = execute(tc.name, tc.arguments, user, db, cfg=cfg)
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
