# 数字分身 + 情绪感知 — 让贾维斯在用户外出时代劳，并感知当下情绪调整回复姿态
#
# 1. 情绪感知：用户消息进 agent 前做一次轻量 LLM 分类（calm/frustrated/tired，失败默认 calm），
#    结果缓存 10 分钟防每句都分类；frustrated/tired 时由 engine 在 system prompt 注入回复收紧指令。
# 2. 数字分身：聊天指令「我不在」开启分身并引导把规则存入 away_rules，「我回来了」关闭；
#    调度器每 tick 检查 enabled 规则，LLM 判定此刻是否需要动作（如日程变更），
#    是则执行并留「数字分身代劳」通知，每规则每天最多动作一次。
import json
import time
from datetime import date, datetime, timedelta

from ..config import settings
from ..models import AwayRule, Conversation, Notification, Schedule, User, UserSetting

# ── 情绪感知 ─────────────────────────────────────────────────────────
MOOD_TTL_SECONDS = 10 * 60          # 情绪分类结果缓存时长
_EMOTION_SYSTEM = (
    "你是情绪识别器。判断用户最近一条消息体现的情绪，只输出一个英文词：calm、frustrated 或 tired。"
    "calm=平静；frustrated=烦躁/不满/着急；tired=疲惫/无力/没精神。"
)
# 注入 system prompt 的收紧指令：frustrated/tired 时开启
MOOD_SUFFIX = "\n\n【用户当前情绪不佳】回复减半、去掉俏皮话与反问、直接给结论"

# user_id → (mood, ts)；进程内缓存，重启即清空
_mood_cache: dict[int, tuple[str, float]] = {}


def get_cached_mood(user_id: int) -> str | None:
    """返回仍在缓存有效期内的情绪；过期/无记录返回 None。"""
    entry = _mood_cache.get(user_id)
    if entry is None:
        return None
    mood, ts = entry
    if time.time() - ts < MOOD_TTL_SECONDS:
        return mood
    del _mood_cache[user_id]
    return None


def _parse_mood(text: str) -> str:
    t = (text or "").strip().lower()
    for mood in ("frustrated", "tired", "calm"):
        if mood in t:
            return mood
    return "calm"


async def classify_mood(user_msg: str, cfg: dict | None, user_id: int) -> str:
    """轻量情绪分类（tools=[]，输出 calm/frustrated/tired 三选一）。

    命中 10 分钟缓存直接返回；未配置 LLM、调用失败或输出无法识别一律默认 calm。
    """
    cached = get_cached_mood(user_id)
    if cached is not None:
        return cached

    # 与 llm.chat 同样的前置守卫：没有可用密钥时不发无谓的分类请求，直接按 calm 处理
    if not (((cfg or {}).get("api_key")) or settings.llm_api_key):
        return "calm"

    from ..agent.llm import chat

    try:
        result = await chat(
            messages=[
                {"role": "system", "content": _EMOTION_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            tools=[],
            cfg=cfg,
        )
    except Exception:
        result = None
    mood = _parse_mood(result.text) if result is not None and not result.error else "calm"
    _mood_cache[user_id] = (mood, time.time())
    return mood


def mood_system_suffix(mood: str) -> str:
    """frustrated/tired 时返回追加进 system prompt 的情绪收紧指令，否则空串。"""
    return MOOD_SUFFIX if mood in ("frustrated", "tired") else ""


# ── 数字分身：外出开关与规则录入 ────────────────────────────────────────
AWAY_ON_KEY = "companion.away_enabled"
AWAY_ON_CMD = "我不在"
AWAY_OFF_CMD = "我回来了"
# 分身执行规则时使用固定标题的专属会话，便于复用
AWAY_CONVERSATION_TITLE = "数字分身"
# UserSetting key 前缀：记录规则最近一次动作日期（YYYY-MM-DD），防同一天重复动作
AWAY_DONE_KEY = "away_rule_done:%d"


def _away_enabled(db, user_id: int) -> bool:
    row = (
        db.query(UserSetting)
        .filter(UserSetting.user_id == user_id, UserSetting.key == AWAY_ON_KEY)
        .first()
    )
    return bool(row and row.value == "1")


def _set_away(db, user_id: int, value: int) -> None:
    row = (
        db.query(UserSetting)
        .filter(UserSetting.user_id == user_id, UserSetting.key == AWAY_ON_KEY)
        .first()
    )
    if row is None:
        db.add(UserSetting(user_id=user_id, key=AWAY_ON_KEY, value=str(value)))
    else:
        row.value = str(value)
    db.commit()


def _enable_away(db, user: User) -> str:
    _set_away(db, user.id, 1)
    return (
        "好的，已开启数字分身。告诉我你不在时要我替你处理的事项，我会记住并在合适的时机代办。\n"
        "例如：「如果周三的会议改期，帮我改到周四」。\n"
        "每条规则单独发给我，说「我回来了」即可关闭分身。"
    )


def _store_rule(db, user: User, rule_text: str) -> str:
    db.add(AwayRule(user_id=user.id, rule_text=rule_text, enabled=1))
    db.commit()
    return f"已记下规则：{rule_text}\n还有别的吗？说「我回来了」关闭分身。"


def _disable_away(db, user: User) -> str:
    _set_away(db, user.id, 0)
    # 关闭分身 = 数字分身时段结束：停用该用户全部外出规则，调度器不再代办
    for rule in db.query(AwayRule).filter(AwayRule.user_id == user.id, AwayRule.enabled == 1).all():
        rule.enabled = 0
    db.commit()
    return "欢迎回来，先生。数字分身已关闭。"


def try_handle_away_command(db, user: User, conversation_id: int, user_msg: str) -> str | None:
    """接管分身指令：返回回复文本表示已处理，返回 None 表示非分身消息交给 agent。

    「我不在」→ 开启分身；「我回来了」→ 关闭；分身开启期间其余消息一律视为规则录入。
    """
    text = (user_msg or "").strip()
    stripped = text.strip(" 　，。！？!?,.~")
    if stripped == AWAY_ON_CMD:
        return _enable_away(db, user)
    if stripped == AWAY_OFF_CMD:
        return _disable_away(db, user)
    if _away_enabled(db, user.id):
        return _store_rule(db, user, text)
    return None


# ── 数字分身：调度器检查与执行 ──────────────────────────────────────────
_RULE_JUDGE_SYSTEM = (
    "你是贾维斯的数字分身，替外出的主人处理事务。根据主人留下的规则和当前情况，"
    "判断此刻是否需要执行动作。只需输出 JSON：{\"need\": true 或 false}。"
    "true 表示此刻需要替主人执行；false 表示无需动作。"
)


def _llm_cfg(db, user_id: int) -> dict:
    from ..user_cfg import get_llm_map

    cfg_map = get_llm_map(db, user_id)
    return {
        "provider": cfg_map.get("llm.provider"),
        "model": cfg_map.get("llm.model"),
        "api_key": cfg_map.get("llm.api_key"),
        "base_url": cfg_map.get("llm.base_url"),
    }


def _today_schedule_lines(db, user_id: int) -> list[str]:
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    events = (
        db.query(Schedule)
        .filter(Schedule.user_id == user_id, Schedule.start_at >= start, Schedule.start_at < end)
        .order_by(Schedule.start_at.asc())
        .all()
    )
    return [f"{e.start_at:%H:%M} {e.title}" for e in events]


def _parse_need(text: str) -> bool:
    t = (text or "").strip()
    try:
        return bool(json.loads(t).get("need"))
    except Exception:
        pass
    # 兜底：LLM 偶尔会带前后缀，截取首个 {…} 再解析
    try:
        start, end = t.find("{"), t.rfind("}") + 1
        if 0 <= start < end:
            return bool(json.loads(t[start:end]).get("need"))
    except Exception:
        pass
    return False


async def _judge_rule(db, user: User, rule: AwayRule, cfg: dict) -> bool:
    """LLM 判定该规则此刻是否需要动作；调用失败/无法解析一律视为不需要。"""
    from ..agent.llm import chat

    context = {
        "现在": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "规则": rule.rule_text,
        "今日日程": _today_schedule_lines(db, user.id),
    }
    try:
        result = await chat(
            messages=[
                {"role": "system", "content": _RULE_JUDGE_SYSTEM},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
            tools=[],
            cfg=cfg,
        )
    except Exception:
        return False
    if result.error:
        return False
    return _parse_need(result.text)


def _rule_done_today(db, rule: AwayRule) -> bool:
    row = (
        db.query(UserSetting)
        .filter(UserSetting.user_id == rule.user_id, UserSetting.key == AWAY_DONE_KEY % rule.id)
        .first()
    )
    return bool(row and row.value == date.today().isoformat())


def _mark_rule_done(db, rule: AwayRule) -> None:
    row = (
        db.query(UserSetting)
        .filter(UserSetting.user_id == rule.user_id, UserSetting.key == AWAY_DONE_KEY % rule.id)
        .first()
    )
    if row is None:
        db.add(UserSetting(user_id=rule.user_id, key=AWAY_DONE_KEY % rule.id, value=date.today().isoformat()))
    else:
        row.value = date.today().isoformat()


async def _execute_rule(db, user: User, rule: AwayRule, cfg: dict) -> str:
    """把规则交给 agent 执行（可调工具）；返回执行结果文本，失败转人话。"""
    from ..agent.engine import run_agent

    conv = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id, Conversation.title == AWAY_CONVERSATION_TITLE)
        .first()
    )
    if conv is None:
        conv = Conversation(user_id=user.id, title=AWAY_CONVERSATION_TITLE)
        db.add(conv)
        db.commit()
        db.refresh(conv)
    try:
        # bypass_away：规则文本是分身要执行的事务，不是新的分身规则，不能再次拦截录入
        reply, _steps, _trace = await run_agent(db, user, conv.id, rule.rule_text, bypass_away=True)
    except Exception as e:
        reply = f"数字分身执行失败: {e}"
    return reply


async def run_away_rules(db) -> list[str]:
    """调度器每 tick 调用：检查启用规则，LLM 判定需要动作则执行并留通知。

    每规则每天最多动作一次（UserSetting 记录动作日期）；单条规则异常回滚跳过，不拖垮其他规则。
    """
    summaries: list[str] = []
    for rule in db.query(AwayRule).filter(AwayRule.enabled == 1).all():
        if _rule_done_today(db, rule):
            continue
        user = db.get(User, rule.user_id)
        if user is None:
            continue
        cfg = _llm_cfg(db, rule.user_id)
        try:
            need = await _judge_rule(db, user, rule, cfg)
            if not need:
                continue
            outcome = await _execute_rule(db, user, rule, cfg)
            _mark_rule_done(db, rule)
            db.add(Notification(user_id=rule.user_id, title="数字分身代劳", content=outcome, kind="away"))
            db.commit()
            summaries.append(f"rule{rule.id}: {outcome[:40]}")
        except Exception:
            db.rollback()
    return summaries
