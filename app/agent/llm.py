# OneFlow LiteLLM 封装 —— 统一入口，隔离外部 LLM 依赖
import asyncio
import json
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import litellm

from ..config import settings

# 瞬时错误（网络抖动/限流/服务端 5xx）：自动重试一次再判定失败
TRANSIENT_ERRORS = (
    litellm.APIConnectionError,
    litellm.Timeout,
    litellm.RateLimitError,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
)


@dataclass
class ToolCall:
    name: str
    arguments: dict  # 已 json.loads 成 dict


@dataclass
class LLMResult:
    text: Optional[str] = None
    tool_call: Optional[ToolCall] = None
    # 思考模型（deepseek-reasoner 等）返回的思维链；DeepSeek 要求多轮原样回传
    reasoning_content: Optional[str] = None
    # True = 调用本身失败（错误提示不应落库进历史）；False = 正常回复/提示
    error: bool = False


# 流式文本增量回调（可同步可异步）
DeltaCallback = Callable[[str], Optional[Awaitable[None]]]


def build_model_id(cfg: dict | None = None) -> str:
    """LiteLLM 需要的 "provider/model" 组合，如 "openai/gpt-5.6-sol"。

    cfg 非空且含非空 provider/model 时用用户配置，否则回退全局默认。
    """
    if cfg and cfg.get("provider") and cfg.get("model"):
        return f"{cfg['provider']}/{cfg['model']}"
    return f"{settings.llm_provider}/{settings.llm_model}"


def _extract_reasoning(msg) -> Optional[str]:
    """从非流式 message 提取思维链：可能挂在属性或 provider_specific_fields 上。"""
    reasoning = getattr(msg, "reasoning_content", None)
    if reasoning is None:
        extra = getattr(msg, "provider_specific_fields", None) or {}
        if isinstance(extra, dict):
            reasoning = extra.get("reasoning_content")
    return reasoning


def _delta_reasoning(delta) -> Optional[str]:
    """从流式 chunk.delta 提取思维链增量（思考模型流式同样带 reasoning_content）。"""
    reasoning = getattr(delta, "reasoning_content", None)
    if reasoning is None:
        extra = getattr(delta, "provider_specific_fields", None) or {}
        if isinstance(extra, dict):
            reasoning = extra.get("reasoning_content")
    return reasoning


async def _notify(callback: Optional[DeltaCallback], text: str) -> None:
    """调用增量回调，兼容同步/异步实现。"""
    if callback is None or not text:
        return
    result = callback(text)
    if asyncio.iscoroutine(result):
        await result


async def _consume_stream(resp, on_delta: Optional[DeltaCallback]) -> LLMResult:
    """汇聚流式响应：正文增量实时回调，工具调用分片拼接，思维链静默累积。"""
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    call_acc: dict[int, dict] = {}
    async for chunk in resp:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = choices[0].delta
        if delta is None:
            continue
        piece = getattr(delta, "content", None)
        if piece:
            content_parts.append(piece)
            await _notify(on_delta, piece)
        rc = _delta_reasoning(delta)
        if rc:
            reasoning_parts.append(rc)
        for frag in getattr(delta, "tool_calls", None) or []:
            idx = getattr(frag, "index", 0) or 0
            acc = call_acc.setdefault(idx, {"name": "", "arguments": ""})
            fn = getattr(frag, "function", None)
            if fn is not None:
                if getattr(fn, "name", None):
                    acc["name"] += fn.name
                if getattr(fn, "arguments", None):
                    acc["arguments"] += fn.arguments
    reasoning = "".join(reasoning_parts) or None
    if call_acc:
        first = call_acc[min(call_acc)]
        try:
            arguments = json.loads(first["arguments"] or "{}")
        except json.JSONDecodeError:
            arguments = {}
        return LLMResult(
            tool_call=ToolCall(name=first["name"], arguments=arguments),
            reasoning_content=reasoning,
        )
    return LLMResult(text="".join(content_parts), reasoning_content=reasoning)


async def chat(
    messages: list,
    tools: list,
    cfg: dict | None = None,
    on_delta: DeltaCallback | None = None,
) -> LLMResult:
    """调用 LLM。支持 function calling，返回 LLMResult（text 或 tool_call）。

    cfg 为每用户配置（可含 provider/model/api_key/base_url），覆盖全局默认。
    on_delta 非空时启用真流式：正文增量实时回调（工具调用轮不回调）。
    调用失败（重试后仍失败）返回 error=True 的 LLMResult，调用方不应将其落库。
    """
    effective_key = (cfg.get("api_key") if cfg else None) or settings.llm_api_key
    if not effective_key:
        return LLMResult(text="LLM 未配置：请先在「设置」页填写你自己的 LLM 密钥后使用")

    kwargs = {
        "model": build_model_id(cfg),
        "messages": messages,
        "api_key": effective_key,
    }
    if tools:  # 空列表不传，避免部分 provider 拒绝空 tools 参数（自学习构建器等纯文本场景）
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    api_base = (cfg.get("base_url") if cfg else None) or settings.llm_base_url
    if api_base:
        kwargs["api_base"] = api_base
    if on_delta is not None:
        kwargs["stream"] = True

    try:
        try:
            resp = await litellm.acompletion(**kwargs)
        except TRANSIENT_ERRORS:
            # 瞬时错误（网络/限流/5xx）：短退避后重试一次
            await asyncio.sleep(1.0)
            resp = await litellm.acompletion(**kwargs)
        if on_delta is not None:
            return await _consume_stream(resp, on_delta)
        msg = resp.choices[0].message
        reasoning = _extract_reasoning(msg)
        if msg.tool_calls and len(msg.tool_calls) > 0:
            tc = msg.tool_calls[0]
            return LLMResult(
                tool_call=ToolCall(
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments or "{}"),
                ),
                reasoning_content=reasoning,
            )
        return LLMResult(text=msg.content or "", reasoning_content=reasoning)
    except Exception as e:
        return LLMResult(text=f"LLM 调用出错: {e}", error=True)
