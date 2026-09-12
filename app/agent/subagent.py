# OneFlow 子智能体 — 总控 Agent 通过 delegate 委派专业子智能体执行子任务
import json

from ..config import settings
from ..tools.registry import execute, schemas
from . import llm as llm_mod
# 子智能体配置：agent_name -> system 人设 + 允许使用的工具
SUB_AGENTS = {
    "life": {
        "system": "你是 OneFlow 的「生活助手」子智能体：为用户安排日程、查询天气、做计算、联网查资料。用简洁中文完成任务后直接给结论。",
        "tools": ["schedule_event", "list_schedule", "get_weather", "calculate", "web_search", "read_webpage"],
    },
    "finance": {
        "system": "你是 OneFlow 的「财务助手」子智能体：为用户记账、查账、做计算、联网查汇率资讯。完成用简洁中文给结论。",
        "tools": ["add_expense", "query_expense", "calculate", "web_search", "read_webpage"],
    },
    "travel": {
        "system": "你是 OneFlow 的「出行助手」子智能体：为用户查天气、查酒店、做计算、联网查目的地信息。完成用简洁中文给结论。",
        "tools": ["get_weather", "search_hotel", "calculate", "web_search", "read_webpage"],
    },
}


def _sub_schemas(tool_names: list[str]) -> list:
    """从全局工具 schemas() 里筛出指定工具白名单的 schema 列表。"""
    allowed = set(tool_names)
    return [s for s in schemas() if s["function"]["name"] in allowed]


def resolve_agent(db, user_id: int, agent_name: str) -> dict | None:
    """解析子智能体：内置优先，其次查该用户的自定义；不存在返回 None。"""
    if agent_name in SUB_AGENTS:
        return SUB_AGENTS[agent_name]
    from ..models import CustomAgent

    row = (
        db.query(CustomAgent)
        .filter(CustomAgent.user_id == user_id, CustomAgent.name == agent_name)
        .first()
    )
    if row is None:
        return None
    try:
        tools = json.loads(row.tools or "[]")
    except ValueError:
        tools = []
    return {"system": row.persona, "tools": tools}


async def run_subagent(db, user, agent_name: str, instruction: str, cfg) -> tuple[str, int]:
    """运行子智能体，返回 (结论文本, 步数)。

    agent_name 未知时抛 ValueError；步数超限时返回失败提示文本。
    """
    agent = resolve_agent(db, user.id, agent_name)
    if agent is None:
        raise ValueError("未知子智能体: " + agent_name)

    sub_tools = _sub_schemas(agent["tools"])
    system = agent["system"]
    messages = [{"role": "user", "content": instruction}]

    max_sub_steps = min(settings.max_steps, 5)
    steps = 0
    call_id = 0

    while True:
        steps += 1
        if steps > max_sub_steps:
            return "子智能体未能在限定步数内完成，调用失败，请让用户在总控重试", steps

        payload = [{"role": "system", "content": system}] + messages
        res = await llm_mod.chat(payload, sub_tools, cfg)

        if res.tool_call is None:
            return (res.text or ""), steps

        tc = res.tool_call
        result = execute(tc.name, tc.arguments, user, db)

        tool_call_id = f"sub_{call_id}"
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
        # 思考模型（deepseek-reasoner 等）要求每条 assistant 消息带回思维链
        if res.reasoning_content:
            assistant_msg["reasoning_content"] = res.reasoning_content
        messages.append(assistant_msg)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(result, ensure_ascii=False),
            }
        )
        # 工具执行失败也继续循环，靠步数上限兜底


async def execute_delegate(db, user, agent_name, instruction, cfg) -> dict:
    """执行 delegate 工具调用：未知 agent 返回失败 dict；子运行异常包装为失败结果。"""
    if resolve_agent(db, user.id, agent_name) is None:
        return {"success": False, "error": f"未知子智能体: {agent_name}，可先用 list_custom_agents 查看"}
    try:
        sub_text, sub_steps = await run_subagent(db, user, agent_name, instruction, cfg)
        return {"success": True, "agent": agent_name, "text": sub_text, "steps": sub_steps}
    except Exception as e:
        return {"success": False, "error": f"子智能体执行失败: {e}"}
