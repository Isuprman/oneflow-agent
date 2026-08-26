# 反向面试 2.0 — 贾维斯主动采访用户补全画像（主题递进版）
# 每周最多一次；UserSetting 记录 interview.theme / interview.week_idx：
# 同一主题连续问 4 周（主题从画像缺失维度里按优先级挑），题目参考上次回答（查记忆），
# 4 周后自动换下一个缺失维度。用户在聊天里以「面试 」前缀回复即写入画像/记忆。
import json
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import Conversation, Notification, ToolCallLog, User, UserMemory, UserSetting

# UserSetting key：上次面试日期（ISO 日期字符串），7 天内不再打扰
LAST_ASKED_KEY = "interview.last_asked"
INTERVAL_DAYS = 7

# UserSetting key：主题周递进
THEME_KEY = "interview.theme"
WEEK_KEY = "interview.week_idx"
THEME_WEEKS = 4

# 主题池（按优先级）：先画像缺失维度，再通用盲区；_theme_done 判定是否已覆盖
_THEMES = [
    {"key": "city", "name": "所在城市", "hint": "你生活/工作的城市"},
    {"key": "nickname", "name": "称呼", "hint": "你希望我怎么称呼你"},
    {"key": "workplace", "name": "工作", "hint": "你的工作或职业"},
    {"key": "home", "name": "居住", "hint": "你住的地方"},
    {"key": "interests", "name": "兴趣爱好", "hint": "你的兴趣爱好"},
    {"key": "habits", "name": "生活习惯", "hint": "你的生活习惯/作息"},
    {"key": "tools", "name": "工具使用偏好", "hint": "你最近最常用的功能用得怎么样"},
]
# 记忆类主题的关键词覆盖判定：记忆里出现过这些词即视为该维度已了解
_THEME_KEYWORDS = {
    "interests": ("喜欢", "爱好", "兴趣", "游戏", "电影", "音乐", "运动", "摄影", "旅行"),
    "habits": ("习惯", "作息", "熬夜", "早起", "睡前", "健身", "跑步", "咖啡"),
}

_QUESTION_SYSTEM = (
    "你是 AI 管家贾维斯。根据素材向用户提一个采访问题：要自然、有好奇心，像朋友闲聊而不是填表。"
    "如果素材里有「上次你的回答」，要在提问里自然承接上次聊到的话题，显得记得用户说过的话。"
    "只输出这一句提问，40字以内。"
)
# 直辖市无「市」后缀也按城市识别；其余靠 市/省 后缀保守判断，拿不准就进记忆（不丢信息）
_MUNICIPALITIES = {"北京", "上海", "天津", "重庆"}
_CITY_PREFIX_RE = re.compile(r"^(我(?:现在)?(?:住在|生活在|在)|家住|坐标)")


def should_interview(db: Session, user_id: int) -> bool:
    """每周最多一次：interview.last_asked 距今不足 INTERVAL_DAYS 则不问。"""
    row = (
        db.query(UserSetting)
        .filter(UserSetting.user_id == user_id, UserSetting.key == LAST_ASKED_KEY)
        .first()
    )
    if row is None or not row.value:
        return True
    try:
        last = date.fromisoformat(row.value.strip())
    except ValueError:
        return True
    return (date.today() - last).days >= INTERVAL_DAYS


def _top_tool(db: Session, user_id: int) -> tuple[str, int] | None:
    """近 7 天该用户最常用工具及次数；无记录返回 None。"""
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=INTERVAL_DAYS)
    rows = (
        db.query(ToolCallLog.tool_name)
        .join(Conversation, ToolCallLog.conversation_id == Conversation.id)
        .filter(Conversation.user_id == user_id, ToolCallLog.created_at >= since)
        .all()
    )
    counts: dict[str, int] = {}
    for (name,) in rows:
        counts[name] = counts.get(name, 0) + 1
    if not counts:
        return None
    name = max(counts, key=counts.get)
    return name, counts[name]


# ---------- 主题周递进 ----------


def _get_setting(db: Session, user_id: int, key: str) -> str:
    row = db.query(UserSetting).filter_by(user_id=user_id, key=key).first()
    return row.value.strip() if row and row.value else ""


def _set_setting(db: Session, user_id: int, key: str, value: str) -> None:
    row = db.query(UserSetting).filter_by(user_id=user_id, key=key).first()
    if row is None:
        db.add(UserSetting(user_id=user_id, key=key, value=value))
    else:
        row.value = value
    db.commit()


def _has_memory_about(db: Session, user_id: int, theme_key: str) -> bool:
    """记忆类主题的覆盖判定：有效记忆里命中关键词即为已了解。"""
    keywords = _THEME_KEYWORDS.get(theme_key)
    if not keywords:
        return True
    rows = (
        db.query(UserMemory)
        .filter(UserMemory.user_id == user_id, UserMemory.status == "active")
        .all()
    )
    return any(any(kw in r.content for kw in keywords) for r in rows)


def _theme_done(db: Session, profile: dict, user_id: int, theme: dict) -> bool:
    """该主题维度是否已被覆盖（画像有值 / 记忆有关键词 / 无素材可问）。"""
    key = theme["key"]
    if key in ("city", "nickname", "workplace", "home"):
        return bool(profile.get(key))
    if key == "tools":
        return _top_tool(db, user_id) is None  # 近 7 天没常用工具 → 没有可问的素材
    return _has_memory_about(db, user_id, key)


def _pick_theme(db: Session, user_id: int, exclude: str | None = None) -> dict | None:
    """按优先级挑一个缺失维度作为面试主题；全齐返回 None。"""
    from ..tools.profile import load_profile

    profile = load_profile(db, user_id)
    for theme in _THEMES:
        if theme["key"] == exclude:
            continue
        if _theme_done(db, profile, user_id, theme):
            continue
        return theme
    return None


def _resolve_theme(db: Session, user_id: int) -> tuple[dict | None, int]:
    """主题周递进：同一主题最多 THEME_WEEKS 周，满周自动换下一个缺失维度。

    返回 (theme, week_idx)；无缺失维度返回 (None, 0)。副作用：持久化 THEME_KEY/WEEK_KEY。
    """
    theme_key = _get_setting(db, user_id, THEME_KEY)
    if theme_key:
        theme = next((t for t in _THEMES if t["key"] == theme_key), None)
        try:
            week = int(_get_setting(db, user_id, WEEK_KEY) or "1")
        except ValueError:
            week = 1
        if theme is not None:
            if week >= THEME_WEEKS:
                nxt = _pick_theme(db, user_id, exclude=theme_key) or theme
                _set_setting(db, user_id, THEME_KEY, nxt["key"])
                _set_setting(db, user_id, WEEK_KEY, "1")
                return nxt, 1
            _set_setting(db, user_id, WEEK_KEY, str(week + 1))
            return theme, week + 1
    theme = _pick_theme(db, user_id)
    if theme is None:
        return None, 0
    _set_setting(db, user_id, THEME_KEY, theme["key"])
    _set_setting(db, user_id, WEEK_KEY, "1")
    return theme, 1


def _last_answer(db: Session, user, theme: dict) -> str | None:
    """上次关于该主题的回答：优先画像值，其次最近一条有效记忆（反向面试 2.0 参考上周答案）。"""
    from ..tools.profile import load_profile

    profile = load_profile(db, user.id)
    if profile.get(theme["key"]):
        return profile[theme["key"]]
    row = (
        db.query(UserMemory)
        .filter(UserMemory.user_id == user.id, UserMemory.status == "active")
        .order_by(UserMemory.updated_at.desc())
        .first()
    )
    return row.content if row else None


def _material(db: Session, user) -> dict | None:
    """按当前主题周次组装提问素材；无缺失维度则 None。"""
    theme, week = _resolve_theme(db, user.id)
    if theme is None:
        return None
    material = {"主题": theme["name"], "第几周": week, "想了解": theme["hint"]}
    last = _last_answer(db, user, theme)
    if last:
        material["上次你的回答"] = last
    return material


async def generate_question(db: Session, user: User, cfg: dict) -> str | None:
    """把主题素材交给 LLM 转成一句自然的提问；失败/空回复返回 None。"""
    from ..agent.llm import chat

    material = _material(db, user)
    if material is None:
        return None
    try:
        result = await chat(
            messages=[
                {"role": "system", "content": _QUESTION_SYSTEM},
                {"role": "user", "content": json.dumps(material, ensure_ascii=False)},
            ],
            tools=[],
            cfg=cfg,
        )
    except Exception:
        return None
    if result.error or not result.text:
        return None
    question = result.text.strip()
    return question[:200] or None


def deliver(db: Session, user_id: int, question: str):
    """问题落成通知并记下本次面试日期（周内节流的标记点）。"""
    today = date.today().isoformat()
    row = (
        db.query(UserSetting)
        .filter(UserSetting.user_id == user_id, UserSetting.key == LAST_ASKED_KEY)
        .first()
    )
    if row is None:
        db.add(UserSetting(user_id=user_id, key=LAST_ASKED_KEY, value=today))
    else:
        row.value = today
    notification = Notification(
        user_id=user_id,
        title="贾维斯想更了解你",
        content=f"{question}\n在聊天里回复：面试 你的回答",
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


def extract_city(text: str) -> str | None:
    """从回答里保守识别城市：带 市/省 后缀，或直辖市裸名；其余返回 None。"""
    t = _CITY_PREFIX_RE.sub("", text).strip(" 。，,.!！?？")
    if not t:
        return None
    if t.endswith(("市", "省")) and 2 <= len(t) <= 11 and "\n" not in t:
        return t
    if t in _MUNICIPALITIES:
        return t
    return None


def handle_answer(db: Session, user: User, answer: str) -> str:
    """面试回答落库：城市类进画像（复用 set_profile 校验），其余进长期记忆。返回感谢话术。"""
    from ..tools.profile import set_profile

    text = (answer or "").strip()
    if not text:
        return "好像没收到内容，再说说？"
    city = extract_city(text)
    if city is not None:
        result = set_profile({"key": "city", "value": city}, user, db)
        if result.get("success"):
            return f"谢谢告诉我！已记住你在{city}，以后天气播报和日程安排都会照这里来。"
    db.add(UserMemory(user_id=user.id, content=text))
    db.commit()
    return "谢谢分享！这条已经写进我的长期记忆，以后我会一直记得。"
