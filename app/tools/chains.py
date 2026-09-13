# 技能链工具 — 把一组指令固化成 agent 可自主调用的组合动作
#
# 执行语义：专用「技能链：{name}」会话内按顺序对每步跑 run_agent（复用情境剧本
# 的顺序执行模式），上一步回复经 {{上一步}} 纯文本插值注入下一步（绝不 eval）。
# 防护：链不可嵌套（模块级运行标志）；步骤数上限；每步回复截断防上下文爆炸。
import asyncio
import concurrent.futures
import json

from ..models import SkillChain
from .registry import tool

MAX_CHAIN_STEPS = 6
# {{上一步}} 注入时的截断长度：防止长回复把后续步骤的上下文撑爆
PREV_REPLY_MAX_CHARS = 800
# 单步 agent 执行超时（秒）
STEP_TIMEOUT_SECONDS = 300

# 运行标志：(user_id, chain_id) 集合——链不可嵌套（链内步骤再触发同链/他链会死循环）
_RUNNING: set[tuple[int, int]] = set()


def _run_agent_sync(db, user, conversation_id: int, instruction: str) -> tuple[str, int, list]:
    """在独立线程跑异步 run_agent：工具由 engine 同步调用，不能直接 await。"""
    async def _call():
        from ..agent.engine import run_agent

        return await run_agent(db, user, conversation_id, instruction)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(_call())).result(timeout=STEP_TIMEOUT_SECONDS)


def _owned_chain(db, user, name: str) -> SkillChain | None:
    return (
        db.query(SkillChain)
        .filter(SkillChain.user_id == user.id, SkillChain.name == name)
        .first()
    )


@tool(
    name="save_skill_chain",
    description=(
        "把一组按顺序执行的指令保存为「技能链」，之后 agent 可用 run_skill_chain 一键执行。"
        "用户表达「以后遇到 X 就先…再…」「把这个流程存下来」时调用；"
        "步骤里可用 {{上一步}} 引用上一步的回复。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "链的短名字，如「雨天流程」"},
            "description": {"type": "string", "description": "这条链做什么（一句话）"},
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "有序指令列表（≤6 步），{{上一步}} 会被替换为上一步的回复",
            },
        },
        "required": ["name", "steps"],
    },
)
def save_skill_chain(args: dict, user, db):
    name = (args.get("name") or "").strip()
    steps = [str(s).strip() for s in (args.get("steps") or []) if str(s).strip()]
    if not name or not steps:
        return {"success": False, "error": "链名与步骤均不能为空"}
    if len(steps) > MAX_CHAIN_STEPS:
        return {"success": False, "error": f"技能链最多 {MAX_CHAIN_STEPS} 步"}
    if _owned_chain(db, user, name) is not None:
        return {"success": False, "error": f"已存在同名技能链「{name}」，可先删除再重建"}
    chain = SkillChain(
        user_id=user.id,
        name=name,
        description=(args.get("description") or "").strip(),
        steps=json.dumps(steps, ensure_ascii=False),
    )
    db.add(chain)
    db.commit()
    return {"success": True, "name": name, "steps": steps}


@tool(name="list_skill_chains", description="列出用户保存的所有技能链。", parameters={"type": "object", "properties": {}})
def list_skill_chains(args: dict, user, db):
    chains = (
        db.query(SkillChain)
        .filter(SkillChain.user_id == user.id)
        .order_by(SkillChain.id.desc())
        .all()
    )
    return {
        "success": True,
        "chains": [
            {
                "name": c.name,
                "description": c.description,
                "steps": json.loads(c.steps),
                "enabled": bool(c.enabled),
            }
            for c in chains
        ],
    }


@tool(
    name="delete_skill_chain",
    description="删除一条技能链。",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "链名"}},
        "required": ["name"],
    },
)
def delete_skill_chain(args: dict, user, db):
    chain = _owned_chain(db, user, (args.get("name") or "").strip())
    if chain is None:
        return {"success": False, "error": "技能链不存在"}
    db.delete(chain)
    db.commit()
    return {"success": True, "name": chain.name}


@tool(
    name="run_skill_chain",
    description=(
        "执行一条已保存的技能链：按顺序逐步执行指令，上一步回复经 {{上一步}} 注入下一步。"
        "适合「一串固定流程」的组合动作。"
    ),
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "链名"}},
        "required": ["name"],
    },
)
def run_skill_chain(args: dict, user, db, cfg=None):
    name = (args.get("name") or "").strip()
    chain = _owned_chain(db, user, name)
    if chain is None or not chain.enabled:
        return {"success": False, "error": f"技能链「{name}」不存在或已停用"}
    key = (user.id, chain.id)
    if key in _RUNNING:
        return {"success": False, "error": "技能链正在执行中，不可嵌套触发"}
    _RUNNING.add(key)
    try:
        from ..models import Conversation

        conv = (
            db.query(Conversation)
            .filter(Conversation.user_id == user.id, Conversation.title == f"技能链：{chain.name}")
            .first()
        )
        if conv is None:
            conv = Conversation(user_id=user.id, title=f"技能链：{chain.name}")
            db.add(conv)
            db.commit()
            db.refresh(conv)

        results = []
        prev_reply = ""
        for idx, instruction in enumerate(json.loads(chain.steps)):
            # {{上一步}} 纯文本替换（绝不 eval）；超长回复截断防上下文爆炸
            step_instruction = instruction.replace(
                "{{上一步}}", prev_reply[:PREV_REPLY_MAX_CHARS]
            )
            try:
                reply, _steps, _trace = _run_agent_sync(db, user, conv.id, step_instruction)
            except Exception as e:
                reply = f"步骤执行失败: {e}"
            results.append({"idx": idx, "instruction": instruction, "reply": reply})
            prev_reply = reply
        return {"success": True, "chain": chain.name, "steps": results}
    finally:
        _RUNNING.discard(key)
