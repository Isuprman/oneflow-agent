# 上下文裁剪测试 — 纯函数，无需数据库
from app.agent.context import MIN_KEEP_MESSAGES, trim_history


def _msgs(n, size=100):
    """构造 n 条 user/assistant 交替消息，每条 content 长 size 字符。"""
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": "字" * size}
        for i in range(n)
    ]


def test_trim_noop_when_within_budget():
    history = _msgs(6)
    assert trim_history(history, budget_chars=10000) == history


def test_trim_drops_oldest_first():
    history = _msgs(10, size=100)  # 共 1000 字符
    trimmed = trim_history(history, budget_chars=350)
    # 预算 350 → 最多留 3 条，但受 MIN_KEEP_MESSAGES 保底
    assert len(trimmed) == max(MIN_KEEP_MESSAGES, 3)
    # 留下的是最旧的被裁掉、最新的保留
    assert trimmed[-1] == history[-1]
    assert trimmed[0] == history[len(history) - len(trimmed)]


def test_trim_keeps_minimum_even_over_budget():
    history = _msgs(6, size=1000)  # 每条都超总预算
    trimmed = trim_history(history, budget_chars=10)
    assert len(trimmed) == MIN_KEEP_MESSAGES
    assert trimmed == history[-MIN_KEEP_MESSAGES:]


def test_trim_does_not_mutate_input():
    history = _msgs(10, size=100)
    snapshot = list(history)
    trim_history(history, budget_chars=250)
    assert history == snapshot


def test_trim_short_history_untouched():
    history = _msgs(MIN_KEEP_MESSAGES, size=500)
    assert trim_history(history, budget_chars=1) == history


def test_trim_counts_reasoning_content():
    history = [
        {"role": "user", "content": "问"},
        {"role": "assistant", "content": "答", "reasoning_content": "思" * 500},
        {"role": "user", "content": "再问"},
        {"role": "assistant", "content": "再答"},
        {"role": "user", "content": "最后一问"},
    ]
    trimmed = trim_history(history, budget_chars=100)
    # 带思维链的超长 assistant 消息应被裁掉，最新 4 条保留
    assert trimmed == history[1:] or len(trimmed) == MIN_KEEP_MESSAGES
