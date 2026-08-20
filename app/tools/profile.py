# 用户画像工具 — Agent 主动维护的结构化画像（城市/称呼等）
from .registry import tool

# 允许写入的画像键（防止 LLM 乱建字段）
ALLOWED_PROFILE_KEYS = {"city", "nickname", "workplace", "home"}
KEY_HINT = "city=所在城市 nickname=称呼 workplace=公司 home=住址"


@tool(
    name="set_profile",
    description="更新用户画像：当用户透露长期有效的个人信息时调用。"
    "key 可选：city（所在城市）/ nickname（称呼）/ workplace（公司）/ home（住址）。"
    "例如用户说'我在上海工作'→ set_profile(key='city', value='上海')。",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": f"画像键：{KEY_HINT}"},
            "value": {"type": "string", "description": "内容，简洁明确"},
        },
        "required": ["key", "value"],
    },
)
def set_profile(args, user, db):
    from ..models import UserProfile

    key = (args.get("key") or "").strip()
    value = (args.get("value") or "").strip()
    if key not in ALLOWED_PROFILE_KEYS:
        return {"success": False, "error": f"不支持的画像键：{key}，可选 {sorted(ALLOWED_PROFILE_KEYS)}"}
    if not value:
        return {"success": False, "error": "value 不能为空"}

    row = (
        db.query(UserProfile)
        .filter(UserProfile.user_id == user.id, UserProfile.key == key)
        .first()
    )
    if row is None:
        row = UserProfile(user_id=user.id, key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()
    return {"success": True, "key": key, "value": value}


@tool(
    name="get_profile",
    description="查看当前用户画像（城市/称呼等已知个人信息），需要个性化决策时先查",
    parameters={"type": "object", "properties": {}},
)
def get_profile(args, user, db):
    from ..models import UserProfile

    rows = db.query(UserProfile).filter(UserProfile.user_id == user.id).all()
    return {"success": True, "profile": {r.key: r.value for r in rows}}


def load_profile(db, user_id: int) -> dict:
    """供 engine/scheduler 直接读取画像（非工具路径）。"""
    from ..models import UserProfile

    rows = db.query(UserProfile).filter(UserProfile.user_id == user_id).all()
    return {r.key: r.value for r in rows}
