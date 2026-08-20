# OneFlow 工具注册表 — 装饰器式注册
# 工具模块统一签名：def <name>(args: dict, user: User, db: SessionLocal) -> dict
_REGISTRY: dict = {}
registry = _REGISTRY


def tool(name: str, description: str, parameters: dict):
    """装饰器：把函数注册进 _REGISTRY，返回原函数。"""

    def decorator(fn):
        _REGISTRY[name] = {
            "fn": fn,
            "description": description,
            "parameters": parameters,
        }
        return fn

    return decorator


def schemas():
    """生成 OpenAI function schema 列表，供 LLM 使用。"""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": info["description"],
                "parameters": info["parameters"],
            },
        }
        for name, info in _REGISTRY.items()
    ]


def execute(name, args, user, db):
    """执行已注册工具；未注册或执行异常时返回 success=False。"""
    if name not in _REGISTRY:
        return {"success": False, "error": f"未知工具: {name}"}
    try:
        return _REGISTRY[name]["fn"](args, user, db)
    except Exception as e:
        return {"success": False, "error": str(e)}


# 让装饰器注册各工具模块。
# 注意：放文件底部以规避循环 import —— 各工具模块需要 `from .registry import tool`，
# 若在顶部 import 工具模块，registry 尚未定义 tool 即会触发 ImportError。
from . import weather, expense, schedule, calculator, hotel, scheduled, web
