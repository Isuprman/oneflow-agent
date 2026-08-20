# 自定义子智能体工具 — 用户自建"专家团队"，delegate 动态路由
import json

from .registry import tool

# 内置保留名：用户自定义不可占用
from ..agent.subagent import SUB_AGENTS

ALLOWED_TOOL_POOL = [
    "get_weather", "calculate", "schedule_event", "list_schedule",
    "add_expense", "query_expense", "search_hotel",
    "web_search", "read_webpage", "remember",
]


@tool(
    name="create_custom_agent",
    description="为用户创建一个自定义子智能体（专属人设+工具白名单），之后可用 delegate 委派给它。"
    "用户说'我想要一个健身教练助手'时使用。",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "子智能体名称（英文短名，如 fitness），不能与已有重名"},
            "persona": {"type": "string", "description": "人设描述，如'你是专业的健身教练，为用户制定训练与饮食建议'"},
            "tools": {"type": "array", "items": {"type": "string"}, "description": f"允许使用的工具列表，可选：{ALLOWED_TOOL_POOL}"},
        },
        "required": ["name", "persona", "tools"],
    },
)
def create_custom_agent(args, user, db):
    from ..models import CustomAgent

    name = (args.get("name") or "").strip()
    persona = (args.get("persona") or "").strip()
    tools = args.get("tools") or []
    if not name or not persona:
        return {"success": False, "error": "name 和 persona 不能为空"}
    if name in SUB_AGENTS:
        return {"success": False, "error": f"名称 {name} 是内置子智能体，请换一个"}
    invalid = [t for t in tools if t not in ALLOWED_TOOL_POOL]
    if invalid:
        return {"success": False, "error": f"不支持的工具：{invalid}，可选 {ALLOWED_TOOL_POOL}"}
    if not tools:
        return {"success": False, "error": "至少要给一个工具"}

    exists = (
        db.query(CustomAgent)
        .filter(CustomAgent.user_id == user.id, CustomAgent.name == name)
        .first()
    )
    if exists is not None:
        return {"success": False, "error": f"已有同名子智能体 {name}，请先删除或换名"}

    agent = CustomAgent(user_id=user.id, name=name, persona=persona, tools=json.dumps(tools))
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return {"success": True, "id": agent.id, "name": name, "tools": tools}


@tool(
    name="list_custom_agents",
    description="列出用户已创建的自定义子智能体",
    parameters={"type": "object", "properties": {}},
)
def list_custom_agents(args, user, db):
    from ..models import CustomAgent

    rows = db.query(CustomAgent).filter(CustomAgent.user_id == user.id).all()
    return {
        "success": True,
        "agents": [
            {"id": r.id, "name": r.name, "persona": r.persona, "tools": json.loads(r.tools or "[]")}
            for r in rows
        ],
    }


@tool(
    name="delete_custom_agent",
    description="删除一个自定义子智能体",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "要删除的子智能体名称"}},
        "required": ["name"],
    },
    requires_confirm=True,
)
def delete_custom_agent(args, user, db):
    from ..models import CustomAgent

    name = (args.get("name") or "").strip()
    agent = (
        db.query(CustomAgent)
        .filter(CustomAgent.user_id == user.id, CustomAgent.name == name)
        .first()
    )
    if agent is None:
        return {"success": False, "error": f"找不到子智能体 {name}"}
    db.delete(agent)
    db.commit()
    return {"success": True, "deleted": name}


def available_agent_names(db, user_id: int) -> list[str]:
    """内置 + 该用户自定义的全部子智能体名（供 delegate schema 动态生成）。"""
    from ..models import CustomAgent

    custom = db.query(CustomAgent).filter(CustomAgent.user_id == user_id).all()
    return list(SUB_AGENTS.keys()) + [c.name for c in custom]
