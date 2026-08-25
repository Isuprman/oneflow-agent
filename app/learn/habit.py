# 夜间习惯分析 → 自动生成技能提案（经验结晶）
# 近 7 天同一 (工具, 参数签名) 用满阈值次 → LLM 起草技能提案 → 走既有审批流。
# 另含上线技能质量反馈环：统计近 7 天成功率，差则自动降级、好则发一次好评。
import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import Conversation, HabitDismissed, LearnSkillEmbedding, Notification, SkillProposal, ToolCallLog, User
from ..user_cfg import get_llm_map

WINDOW_DAYS = 7
MIN_COUNT = 3
# 反馈环阈值：近 7 天总调用 ≥5 次才统计；<50% 降级，≥90% 发好评（终身一次）
FEEDBACK_MIN_CALLS = 5
DEGRADE_RATE = 50
PRAISE_RATE = 90
_FEEDBACK_MARKER = "[反馈环]"
_DEGRADE_MARK = "[反馈环] 已自动降级"
_PRAISE_MARK = "[反馈环] 好评"
_DRAFT_SYSTEM = (
    "你是行为模式分析师。根据用户的重复工具使用记录，起草一条『学会新能力』的提案描述："
    "要抽象成什么工具、固定参数是什么、能省掉什么重复操作。只输出描述文本，80字内。"
)


def _now():
    return datetime.now(timezone.utc)


def pattern_signature(tool_name: str, arguments: str | None) -> str:
    try:
        normalized = json.dumps(json.loads(arguments or "{}"), sort_keys=True, ensure_ascii=False)
    except Exception:
        normalized = arguments or ""
    raw = f"{tool_name}|{normalized}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def collect_patterns(db: Session, user_id: int) -> list[dict]:
    """近 7 天 (工具, 参数签名) 聚类，count≥3 的候选模式（限该用户）。"""
    since = _now().replace(tzinfo=None) - timedelta(days=WINDOW_DAYS)
    rows = (
        db.query(ToolCallLog)
        .join(Conversation, ToolCallLog.conversation_id == Conversation.id)
        .filter(Conversation.user_id == user_id, ToolCallLog.created_at >= since)
        .all()
    )
    groups: dict[str, dict] = {}
    for r in rows:
        sig = pattern_signature(r.tool_name, r.arguments)
        g = groups.setdefault(sig, {"tool_name": r.tool_name, "arguments": r.arguments or "{}", "count": 0})
        g["count"] += 1
    return [{"pattern_hash": h, **g} for h, g in groups.items() if g["count"] >= MIN_COUNT]


async def run_daily_proposals(db: Session) -> list[str]:
    """对每个用户跑模式聚类并生成习惯提案（含通知）。返回摘要列表。"""
    from ..agent.llm import chat

    summaries: list[str] = []
    for user in db.query(User).all():
        cfg_map = get_llm_map(db, user.id)
        if not cfg_map.get("llm.api_key"):
            continue
        cfg = {"provider": cfg_map.get("llm.provider"), "model": cfg_map.get("llm.model"),
               "api_key": cfg_map.get("llm.api_key"), "base_url": cfg_map.get("llm.base_url")}
        pending_titles = {
            p.title for p in db.query(SkillProposal)
            .filter_by(user_id=user.id, status="pending").all()
        }
        dismissed = {
            d.pattern_hash for d in
            db.query(HabitDismissed).filter_by(user_id=user.id).all()
        }
        for pat in collect_patterns(db, user.id):
            if pat["pattern_hash"] in dismissed:
                continue
            title = f"习惯提案：{pat['tool_name']}"
            record = f"{pat['tool_name']}（同样参数已重复 {pat['count']} 次）"
            if title in pending_titles:
                continue
            draft = f"把「{record}」沉淀为一个可复用的新工具"
            try:
                result = await chat(
                    messages=[
                        {"role": "system", "content": _DRAFT_SYSTEM},
                        {"role": "user", "content": json.dumps(
                            {"工具": pat["tool_name"], "最近参数": pat["arguments"], "使用次数": pat["count"]},
                            ensure_ascii=False)},
                    ],
                    tools=[],
                    cfg=cfg,
                )
                if result.text and not result.error:
                    draft = result.text.strip()[:300]
            except Exception:
                pass
            proposal = SkillProposal(
                user_id=user.id, slug="", title=title,
                description=draft, status="pending", tool_code="", test_code="",
                test_output=f"来源：夜间习惯分析（{record}）", required_keys="{}", branch="",
            )
            db.add(proposal)
            db.commit()
            db.refresh(proposal)
            db.add(Notification(
                user_id=user.id,
                title="要不要让贾维斯学会新技能？",
                content=(f"我发现你最近经常：{record}。\n"
                         f"提案 #{proposal.id} 已就绪：在聊天里发送「{draft[:60]}」，"
                         "确认后我就开始学习；不感兴趣就回复「拒绝 "
                         f"{proposal.id}」并说明该模式不再提醒。"),
            ))
            db.commit()
            summaries.append(f"user{user.id}: {draft[:60]}")
    return summaries


def _latest_approved_proposal(db: Session, user_id: int, slug: str) -> SkillProposal | None:
    """该 (user, slug) 最新一条已上线（approved）的提案；降级/好评都记在它身上。"""
    rows = (
        db.query(SkillProposal)
        .filter(SkillProposal.user_id == user_id, SkillProposal.slug == slug)
        .order_by(SkillProposal.id.desc())
        .all()
    )
    for p in rows:
        if p.status == "approved":
            return p
    return None


def _skill_stats(db: Session, user_id: int, slug: str, since) -> tuple[int, int]:
    """近 7 天该技能的工具调用 (总次数, 成功次数)。归因保守：只看 success 字段。"""
    rows = (
        db.query(ToolCallLog.success)
        .join(Conversation, ToolCallLog.conversation_id == Conversation.id)
        .filter(
            Conversation.user_id == user_id,
            ToolCallLog.tool_name == slug,
            ToolCallLog.created_at >= since,
        )
        .all()
    )
    total = len(rows)
    ok = sum(1 for (s,) in rows if s)
    return total, ok


async def run_skill_quality_check(db: Session) -> list[str]:
    """上线技能运行质量反馈环：差评自动降级 + 好评一次性通知。

    已上线技能 = LearnSkillEmbedding 全部 (user_id, slug)。归因保守：
    只看 ToolCallLog.success，不做参数分析；降级后用户重新学习即可覆盖恢复。
    """
    summaries: list[str] = []
    live = db.query(LearnSkillEmbedding.user_id, LearnSkillEmbedding.slug).all()
    since = _now().replace(tzinfo=None) - timedelta(days=WINDOW_DAYS)
    for user_id, slug in live:
        proposal = _latest_approved_proposal(db, user_id, slug)
        if proposal is None:
            continue
        total, ok = _skill_stats(db, user_id, slug, since)
        if total < FEEDBACK_MIN_CALLS:
            continue  # 样本太少不下结论
        rate = round(ok / total * 100)
        if rate < DEGRADE_RATE and _DEGRADE_MARK not in (proposal.test_output or ""):
            proposal.status = "failed"
            proposal.test_output = (
                f"{proposal.test_output}\n{_FEEDBACK_MARKER} 近7天成功率 {rate}%，已自动降级"
            ).strip()
            db.commit()
            db.add(Notification(
                user_id=user_id,
                title="技能质量提醒",
                content=(f"技能「{slug}」近7天被调用 {total} 次，仅成功 {ok} 次"
                         f"（成功率 {rate}%），低于阈值，我已把它自动降级下线。"
                         "如果还需要这个能力，在聊天里重新发起学习即可恢复。"),
            ))
            db.commit()
            summaries.append(f"user{user_id}: {slug} 已自动降级（成功率 {rate}%）")
        elif rate >= PRAISE_RATE and _PRAISE_MARK not in (proposal.test_output or ""):
            proposal.test_output = (
                f"{proposal.test_output}\n{_PRAISE_MARK} 通知已发送（近7天成功率 {rate}%）"
            ).strip()
            db.commit()
            db.add(Notification(
                user_id=user_id,
                title=f"{slug} 技能运行良好",
                content=(f"技能「{slug}」近7天被调用 {total} 次，成功率 {rate}%，运行稳定可靠。"),
            ))
            db.commit()
            summaries.append(f"user{user_id}: {slug} 运行良好（成功率 {rate}%）")
    return summaries
