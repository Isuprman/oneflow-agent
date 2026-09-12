# 工具调用确认：信任旋钮分级拦截 + 确认/取消口令匹配 + 高危操作人话摘要。
import json

from ..tools.registry import needs_confirmation

# 确认/取消口令（语音场景下宽松匹配前缀）
CONFIRM_PHRASES = ("确认", "是的", "好的", "对", "可以", "没问题", "执行", "嗯", "要")
CANCEL_PHRASES = ("取消", "不要", "算了", "不用")

# auto 档下仍强制确认的高危操作：删除类不可逆操作。
# 新增不可恢复的写操作时在此登记；普通写操作（记账/定时任务增删）auto 档直接放行。
HIGH_RISK_TOOLS = frozenset({"delete_custom_agent"})


def _needs_confirm(tool_name: str, trust_level: str) -> bool:
    """按信任等级决定工具调用是否进确认分支。

    ask_all：每个工具调用前都确认（复用高危 pending 机制）；
    standard：现状——仅高危写操作（requires_confirm）确认；
    auto：普通写操作直接执行，删除类高危仍强制确认。
    delegate 始终除外：由引擎异步委派，进 pending 会导致确认后 execute 失败。
    """
    if tool_name == "delegate":
        return False
    if trust_level == "ask_all":
        return True
    if not needs_confirmation(tool_name):
        return False
    return trust_level != "auto" or tool_name in HIGH_RISK_TOOLS


def _is_confirm(text: str) -> bool:
    t = text.strip()
    return any(t == p or t.startswith(p) for p in CONFIRM_PHRASES)


def _is_cancel(text: str) -> bool:
    t = text.strip()
    return any(t == p or t.startswith(p) for p in CANCEL_PHRASES)


def _pending_summary(tool_name: str, args: dict) -> str:
    """高危操作的确认描述（给用户看的人话）。"""
    if tool_name == "add_expense":
        category = args.get("category") or "未分类"
        note = f"，备注：{args['note']}" if args.get("note") else ""
        return f"我将为您记一笔支出：{args.get('amount')} 元（{category}）{note}"
    if tool_name == "create_scheduled_task":
        return (
            f"我将创建定时任务「{args.get('title')}」"
            f"（{args.get('kind')}，{int(args.get('hour', 0)):02d}:{int(args.get('minute') or 0):02d} 执行）"
        )
    if tool_name == "cancel_scheduled_task":
        return f"我将取消定时任务（id={args.get('task_id')}）"
    if tool_name == "delete_custom_agent":
        return f"我将删除自定义子智能体「{args.get('name')}」"
    return f"我将执行高危操作 {tool_name}({json.dumps(args, ensure_ascii=False)})"
