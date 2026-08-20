# OneFlow 长期记忆工具
from .registry import tool


@tool(
    name="remember",
    description="记住一条关于用户的长期信息（偏好/事实/结论），供以后的问答复用；当用户透露值得长期记住的事实或偏好时调用",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string", "description": "要记住的内容，一句话"}},
        "required": ["text"],
    },
)
def remember(args, user, db):
    text = (args.get("text") or "").strip()
    if not text:
        return {"success": False, "error": "内容不能为空"}
    from ..models import UserMemory

    m = UserMemory(user_id=user.id, content=text)
    db.add(m)
    db.commit()
    db.refresh(m)
    return {"success": True, "id": m.id, "content": m.content}
