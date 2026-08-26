# 年度体检 — 抽样用户最近成功调用为「金题集」，每周重放打分并投递健康通知
#
# 与 GET /api/checkup 无关：金题生成与重放都挂在 scheduler（每用户周节流），
# 重放用 registry.execute 构造「简化的直接工具调用」而非跑全 agent，无 LLM 开销。
import json
import logging
from datetime import date

from sqlalchemy.orm import Session

from ..models import Conversation, Notification, ToolCallLog, User, UserSetting

logger = logging.getLogger(__name__)

GOLDEN_KEY = "checkup.golden"
LAST_RUN_KEY = "checkup.last_run"
WEEKLY_DAYS = 7
SAMPLE_LIMIT = 20
SUCCESS_THRESHOLD = 0.8
WARN_MARK = "⚠️ "
TITLE_TMPL = "贾维斯体检：{n} 项能力 {rate}% 正常"


def run_checkup(db: Session, user_id: int) -> dict:
    """抽样最近 SAMPLE_LIMIT 次成功调用作为「金题集」，落库 checkup.golden（覆盖旧）。

    返回 {"count", "golden"}；没有成功调用时 golden 为空（仍覆盖旧集）。
    """
    rows = (
        db.query(ToolCallLog)
        .join(Conversation, ToolCallLog.conversation_id == Conversation.id)
        .filter(Conversation.user_id == user_id, ToolCallLog.success == 1)
        .order_by(ToolCallLog.id.desc())
        .limit(SAMPLE_LIMIT)
        .all()
    )
    golden = []
    for r in reversed(rows):  # 时间正序：老的在前
        try:
            arguments = json.loads(r.arguments or "{}")
        except (ValueError, TypeError):
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        golden.append({
            "tool": r.tool_name,
            "arguments": arguments,
            "result_summary": _summarize(r.result),
        })
    value = json.dumps(golden, ensure_ascii=False)
    row = db.query(UserSetting).filter(UserSetting.user_id == user_id, UserSetting.key == GOLDEN_KEY).first()
    if row is None:
        db.add(UserSetting(user_id=user_id, key=GOLDEN_KEY, value=value))
    else:
        row.value = value
    db.commit()
    return {"count": len(golden), "golden": golden}


def load_golden(db: Session, user_id: int) -> list[dict]:
    """读取该用户已落库的金题集；缺失/损坏返回空列表。"""
    row = db.query(UserSetting).filter(UserSetting.user_id == user_id, UserSetting.key == GOLDEN_KEY).first()
    if row is None or not row.value:
        return []
    try:
        data = json.loads(row.value)
    except (ValueError, TypeError):
        return []
    return data if isinstance(data, list) else []


def replay_golden(db: Session, user: User, golden: list[dict]) -> list[dict]:
    """对金题集逐条重放：构造简化直接工具调用（registry.execute），不做全 agent。

    每条返回 {tool, arguments, result_summary, ok, detail}；ok = 重放结果 success=True。
    """
    from ..tools.registry import execute

    results = []
    for item in golden:
        tool_name = item.get("tool", "")
        args = item.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        try:
            out = execute(tool_name, args, user, db)
        except Exception as e:  # 兜底：工具实现抛异常也记为失败
            out = {"success": False, "error": str(e)}
        results.append({
            "tool": tool_name,
            "arguments": args,
            "result_summary": item.get("result_summary", ""),
            "ok": bool(out.get("success")),
            "detail": json.dumps(out, ensure_ascii=False)[:200],
        })
    return results


def score(results: list[dict]) -> dict:
    """统计重放成功率：{total, ok, rate}（rate 为整数百分比）。"""
    total = len(results)
    ok = sum(1 for r in results if r.get("ok"))
    rate = round(ok * 100 / total) if total else 0
    return {"total": total, "ok": ok, "rate": rate}


def run_weekly_checkups(db: Session) -> list[str]:
    """对每个用户：周节流 → 刷新金题集 → 重放打分 → 写健康通知。

    单人失败回滚跳过，不拖垮其他用户；返回各用户摘要供调度日志。
    """
    summaries: list[str] = []
    for user in db.query(User).all():
        try:
            summary = _checkup_for_user(db, user)
            if summary:
                summaries.append(summary)
        except Exception:
            logger.warning("年度体检 user%s 失败，跳过", user.id, exc_info=True)
            db.rollback()
    return summaries


def _should_run(db: Session, user_id: int) -> bool:
    """每周最多一次：checkup.last_run 距今不足 WEEKLY_DAYS 则跳过。"""
    row = db.query(UserSetting).filter(UserSetting.user_id == user_id, UserSetting.key == LAST_RUN_KEY).first()
    if row is None or not row.value:
        return True
    try:
        last = date.fromisoformat(row.value.strip())
    except ValueError:
        return True
    return (date.today() - last).days >= WEEKLY_DAYS


def _mark_run(db: Session, user_id: int) -> None:
    row = db.query(UserSetting).filter(UserSetting.user_id == user_id, UserSetting.key == LAST_RUN_KEY).first()
    if row is None:
        db.add(UserSetting(user_id=user_id, key=LAST_RUN_KEY, value=date.today().isoformat()))
    else:
        row.value = date.today().isoformat()


def _checkup_for_user(db: Session, user: User) -> str | None:
    if not _should_run(db, user.id):
        return None
    _mark_run(db, user.id)
    db.commit()

    golden = run_checkup(db, user.id)["golden"]
    if not golden:
        return None  # 没有金题集（尚无成功调用），本次不打扰

    results = replay_golden(db, user, golden)
    stats = score(results)
    _notify(db, user.id, results, stats)
    return f"user{user.id}: {stats['total']} 项 {stats['rate']}% 正常"


def _notify(db: Session, user_id: int, results: list[dict], stats: dict) -> None:
    """写体检通知：成功率 <80% 时标题加 ⚠️ 并在正文列出异常项。"""
    title = TITLE_TMPL.format(n=stats["total"], rate=stats["rate"])
    failed = [r for r in results if not r.get("ok")]
    if stats["rate"] < SUCCESS_THRESHOLD * 100:
        title = WARN_MARK + title
    if failed:
        lines = [f"- {r['tool']}: {r.get('result_summary') or r.get('detail') or '无输出'}" for r in failed]
        content = "以下能力重放异常：\n" + "\n".join(lines)
    else:
        content = "金题集全部重放通过，各项能力运行正常。"
    db.add(Notification(user_id=user_id, title=title, content=content, kind="checkup"))
    db.commit()


def _summarize(raw: str, limit: int = 120) -> str:
    """结果摘要：JSON 解析后截断；解析失败用原文截断。"""
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        text = json.dumps(json.loads(text), ensure_ascii=False)
    except (ValueError, TypeError):
        pass
    return text[:limit]
