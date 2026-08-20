# delegate — 让总控 Agent 把子任务委派给专业子智能体执行
from .registry import tool


@tool(
    name="delegate",
    description=(
        "把子任务委派给专门的子智能体执行，完成后返回其结论。内置子智能体："
        "life（生活/日程/天气/计算）、finance（财务/记账/查账）、travel（出行/天气/酒店）；"
        "用户还可能自建了其他子智能体（可用 list_custom_agents 查看）。"
        "当用户的任务正好明确对应某个专业子智能体时使用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_name": {"type": "string", "description": "life | finance | travel"},
            "instruction": {"type": "string", "description": "交给子智能体的明确指令，含所有必要细节"},
        },
        "required": ["agent_name", "instruction"],
    },
)
def delegate(args, user, db):
    # 该函数不会被 execute() 真正调用——委派由总控 engine 拦截异步执行。
    # 仅用于把 schema 注册进 schemas()。若意外走到这里说明引擎没拦截。
    return {"success": False, "error": "delegate 应由总控引擎处理，不应直接作为普通工具执行"}
