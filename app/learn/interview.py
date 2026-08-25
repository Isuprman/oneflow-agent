# 反向面试 — 贾维斯主动采访用户补全画像
# 每周最多一次：找画像盲区（缺城市 / 无长期记忆 / 最常用工具偏好）→ LLM 把素材
# 转成一句自然的提问 → 通知投递；用户在聊天里以「面试 」前缀回复即写入画像/记忆。
import json
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import Conversation, Notification, ToolCallLog, User, UserMemory, UserSetting

# UserSetting key：上次面试日期（ISO 日期字符串），7 天内不再打扰
LAST_ASKED_KEY = "interview.last_asked"
INTERVAL_DAYS = 7

_QUESTION_SYSTEM = (
    "你是 AI 管家贾维斯。根据素材向用户提一个采访问题：要自然、有好奇心，像朋友闲聊而不是填表。"
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


def _material(db: Session, user) -> dict | None:
    """找画像盲区，返回提问素材；三类盲区都没有则 None。"""
    from ..tools.profile import load_profile

    profile = load_profile(db, user.id)
    if not profile.get("city"):
        return {"盲区": "不知道用户所在的城市", "用途": "天气播报与日程安排的个性化"}
    memory_count = db.query(UserMemory).filter(UserMemory.user_id == user.id).count()
    if memory_count == 0:
        return {"盲区": "还没有任何关于用户的长期记忆", "想了解": "一件用户最希望我长期记住的事（偏好/习惯/事实）"}
    top = _top_tool(db, user.id)
    if top is None:
        return None
    return {"盲区": "使用偏好", "近7天最常用工具": top[0], "调用次数": top[1], "想了解": "对这个工具的使用感受与期待"}


async def generate_question(db: Session, user: User, cfg: dict) -> str | None:
    """把盲区素材交给 LLM 转成一句自然的提问；失败/空回复返回 None。"""
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
