# OneFlow 上下文管理 —— 历史消息按预算裁剪，防长会话撑爆窗口/费用飙升
from ..config import settings

# 无论预算多紧，至少保留最近几条消息，保证对话有最小上下文
MIN_KEEP_MESSAGES = 4


def _estimate_chars(messages: list) -> int:
    """粗估消息列表的 token 占用（按字符数，中文约 1 字/token，含思维链）。"""
    total = 0
    for m in messages:
        for key in ("content", "reasoning_content"):
            value = m.get(key)
            if isinstance(value, str):
                total += len(value)
        # tool_calls 的 arguments 也计入
        for call in m.get("tool_calls") or []:
            fn = call.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                total += len(args)
    return total


def trim_history(history: list, budget_chars: int | None = None) -> list:
    """超预算时从最旧消息开始裁剪，返回裁剪后的新列表（不改原列表）。

    - 预算默认取 settings.context_budget_chars
    - 至少保留最近 MIN_KEEP_MESSAGES 条，即使仍超预算也不再裁
    - 裁剪单位是单条消息；tool/tool_call 配对消息可能被拆开，
      LLM 对缺失 tool 结果的容忍度由步内重试兜底（历史场景罕见）
    """
    budget = budget_chars if budget_chars is not None else settings.context_budget_chars
    if budget <= 0 or len(history) <= MIN_KEEP_MESSAGES:
        return list(history)
    result = list(history)
    start = 0
    while (
        len(result) - start > MIN_KEEP_MESSAGES
        and _estimate_chars(result[start:]) > budget
    ):
        start += 1
    return result[start:]
