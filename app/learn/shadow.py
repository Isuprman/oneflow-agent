# 影子模式 — 会话内实时识别重复流程，提议存成情境剧本
#
# 夜间习惯分析是 T+1 的；这里做实时影子：同一会话 30 分钟窗口内用户连发 ≥3 条指令，
# 贾维斯通过 Notification 主动提议——「刚才这套流程要不要存成剧本？」
# 用户在聊天里回复「存为剧本」，chat_stream 检测到该前缀即调 confirm_scene 落库。
import time

from sqlalchemy.orm import Session

from ..models import Notification, Scene, User

# 窗口与阈值：30 分钟内 user 消息 ≥3 条视为一套可沉淀流程
WINDOW_SECONDS = 30 * 60
THRESHOLD = 3
MAX_TRACK = 10          # 每会话只记最近 10 条，防内存膨胀
NAME_PREFIX_CHARS = 6   # 剧本名取首条指令前 6 字

CONFIRM_PREFIX = "存为剧本"

# conv_id → {"texts": [(ts, msg)], "proposed": bool}；进程内状态，重启即清空
conv_tracker: dict[int, dict] = {}


def _scene_name(first_msg: str) -> str:
    head = first_msg.strip()[:NAME_PREFIX_CHARS].strip() or "流程"
    return f"{head}剧本"


def note_and_maybe_propose(db: Session, conv_id: int, user_id: int, user_msg: str) -> str | None:
    """记录用户消息；命中阈值且未提议过 → 发影子模式提议通知。返回 None（提议走通知通道）。"""
    entry = conv_tracker.setdefault(conv_id, {"texts": [], "proposed": False})
    now = time.time()
    texts: list[tuple[float, str]] = entry["texts"]
    msg = (user_msg or "").strip()
    if msg:
        texts.append((now, msg))
        del texts[:-MAX_TRACK]

    recent = [m for ts, m in texts if now - ts <= WINDOW_SECONDS]
    if len(recent) < THRESHOLD or entry["proposed"]:
        return None

    entry["proposed"] = True
    name = _scene_name(recent[0])
    steps_preview = "\n".join(f"  {i}. {s}" for i, s in enumerate(recent, start=1))
    content = (
        f"我注意到你刚才连续执行了 {len(recent)} 步操作，像是固定流程：\n{steps_preview}\n"
        f"要不要存成剧本《{name}》？在聊天里回复：{CONFIRM_PREFIX}"
    )
    db.add(Notification(user_id=user_id, title="影子模式", content=content, kind="shadow"))
    db.commit()
    return None


def confirm_scene(db: Session, user: User, conv_id: int) -> str:
    """「存为剧本」指令：把 tracker 里的指令原文落库成 Scene，返回给用户的确认文案。"""
    entry = conv_tracker.get(conv_id)
    if not entry or not entry["texts"]:
        return "这个会话没有可存的流程记录，多聊几轮我再帮你观察。"
    steps = [m.strip() for _, m in entry["texts"] if m.strip()][:10]
    if not steps:
        del conv_tracker[conv_id]
        return "这个会话没有可存的流程记录，多聊几轮我再帮你观察。"

    base = _scene_name(steps[0])
    name, seq = base, 2
    while (
        db.query(Scene).filter(Scene.user_id == user.id, Scene.name == name).first()
        is not None
    ):
        name = f"{base}{seq}"  # 同名已存在 → 追加序号，不报错不打断
        seq += 1
    scene = Scene(user_id=user.id, name=name, steps="\n".join(steps), enabled=1)
    db.add(scene)
    db.commit()
    db.refresh(scene)
    del conv_tracker[conv_id]
    return f"已创建剧本《{scene.name}》，以后说 场景 {scene.name} 一键执行"
