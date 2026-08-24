# 聊天钩子 — 让贾维斯在对话里直接完成「学习」闭环
#
# 支持的说法：
#   学习请求：「你要是能查快递就好了」「教你会翻译古文」「给自己加个记账工具」
#   审批指令：「批准 12」「拒绝 12」「key 12 DEMO_API_KEY=sk-xxx」
#
# 学习请求走两段式确认：首次命中先做 ASR 纠错并复述，等用户确认后才真正构建；
# 构建期间通过 on_progress 向流式接口直播进度。
# 返回 None 表示与本流程无关，交给正常 agent 处理。
import asyncio
import json
import re
import time

from ..models import Message, User
from . import service

# 触发词保守列表：宁可不触发也不误劫持正常聊天
_ACQUIRE_RE = re.compile(r"你要是能|要是你能|教你会|给你学会|学会一[个项]|给自己加[个一]|装个新工具|加个新技能")

_APPROVE_RE = re.compile(r"^批准\s*(\d+)\s*$")
_REJECT_RE = re.compile(r"^拒绝\s*(\d+)\s*$")
_KEY_RE = re.compile(r"^key\s+(\d+)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\S+)\s*$", re.I)

_CONFIRM_RE = re.compile(r"^(确认|确定|对|是的?|没错|可以|开始吧?|嗯+)$")
_CANCEL_RE = re.compile(r"^(取消|算了|不用了?)$")

# user_id → {"raw": 确认中的需求原文, "ts": 进入时间}；进程内状态，重启即清空
pending_intents: dict[int, dict] = {}

_PROGRESS_STAGES = ("正在理解需求…", "正在设计工具与测试…", "沙箱验证中…")
_PROGRESS_DONE = "候选已提交，等待确认上线"


def _save_pair(db, conversation_id: int, user_msg: str, reply: str) -> None:
    db.add(Message(conversation_id=conversation_id, role="user", content=user_msg))
    db.add(Message(conversation_id=conversation_id, role="assistant", content=reply))
    db.commit()


def _proposal_reply(p) -> str:
    lines = [f"我在学这个新能力，候选已经准备好了：{p.title or p.slug}"]
    if p.status == "failed":
        lines = ["这次没学会，构建失败了。日志如下：", (p.test_output or "")[-800:]]
        return "\n".join(lines)
    keys = json.loads(p.required_keys or "{}")
    lines.append(f"测试已通过，提案编号 #{p.id}。")
    if keys:
        lines.append("它需要这些密钥才能上线：")
        for name, desc in keys.items():
            lines.append(f"  · {name}（{desc}）→ 发送「key {p.id} {name}=你的密钥」")
        lines.append(f"填完后发送「批准 {p.id}」即可上线。不想学了就发「拒绝 {p.id}」。")
    else:
        lines.append(f"发送「批准 {p.id}」我就把它合并上线；不想学了就发「拒绝 {p.id}」。")
    lines.append(f"[LEARN_PROPOSAL]{json.dumps({'id': p.id, 'slug': p.slug, 'title': p.title, 'required_keys': keys, 'status': p.status}, ensure_ascii=False)}[/LEARN_PROPOSAL]")
    return "\n".join(lines)


def _confirm_prompt(raw: str) -> str:
    return (
        f"确认一下：你想让贾维斯学会——【{raw}】。\n"
        "回复「确认」我就开始学；说错了就直接把正确的需求发给我；说「取消」放弃。"
    )


async def correct_asr_text(text: str, cfg: dict | None) -> str:
    """语音识别纠错：让 LLM 结合语境修同音字错误；失败/超时原样返回。"""
    from ..agent.llm import chat

    async def _call():
        return await chat(
            messages=[
                {"role": "system", "content": "这句可能来自语音识别，含同音字错误。结合语境输出最可能的正确原句，只输出纠正后的句子"},
                {"role": "user", "content": text},
            ],
            tools=[],
            cfg=cfg,
        )

    try:
        result = await asyncio.wait_for(_call(), timeout=8)
    except Exception:
        return text
    if result.error or not result.text:
        return text
    corrected = result.text.strip()
    return corrected or text


def is_learn_message(text: str) -> bool:
    """廉价预判（纯正则），供流式路由决定是否进入自学习分支。

    待确认状态的跟进消息（确认/取消/纠正）不经过这里——路由侧用 pending_intents 判断。
    """
    t = text.strip()
    return bool(_ACQUIRE_RE.search(t) or _APPROVE_RE.match(t) or _REJECT_RE.match(t) or _KEY_RE.match(t))


def _llm_cfg(db, user: User) -> dict:
    from ..user_cfg import get_llm_map

    cfg_map = get_llm_map(db, user.id)
    return {
        "provider": cfg_map.get("llm.provider"),
        "model": cfg_map.get("llm.model"),
        "api_key": cfg_map.get("llm.api_key"),
        "base_url": cfg_map.get("llm.base_url"),
    }


async def try_handle(db, user: User, conversation_id: int, user_msg: str, on_progress=None):
    """返回 reply_text|None。None = 非本流程消息。

    on_progress: 构建各阶段的进度回调（str -> None），供流式接口直播。
    """
    text = user_msg.strip()

    # ── 待确认流：优先于一切意图检测（审批指令除外）──
    entry = pending_intents.get(user.id)
    is_cmd = bool(_APPROVE_RE.match(text) or _REJECT_RE.match(text) or _KEY_RE.match(text))
    if entry and not is_cmd:
        if _CANCEL_RE.match(text):
            del pending_intents[user.id]
            reply = "好的，已取消。"
            _save_pair(db, conversation_id, user_msg, reply)
            return reply
        if entry.get("kind") == "offer_reuse":
            m_up = re.match(r"^升级\s*(.*)$", text)
            new_raw = m_up.group(1).strip() if m_up else ""
            if _CONFIRM_RE.match(text) or (m_up and not new_raw):
                # 已会的技能没有「确认构建」一说：引导走升级或取消
                reply = "请回复「升级」+ 新的需求描述来升级它，或回复「取消」。"
                _save_pair(db, conversation_id, user_msg, reply)
                return reply
            if new_raw:
                # 剥离前缀，按新需求回到正常确认流（重新复述等确认）
                pending_intents[user.id] = {"raw": new_raw, "ts": time.time(), "kind": "confirm"}
                reply = _confirm_prompt(new_raw)
                _save_pair(db, conversation_id, user_msg, reply)
                return reply
            # 其余消息落入下方既有纠正逻辑
        if not _CONFIRM_RE.match(text):
            # 视为纠正：更新需求原文，重新等待确认
            pending_intents[user.id] = {"raw": text, "ts": time.time()}
            reply = _confirm_prompt(text)
            _save_pair(db, conversation_id, user_msg, reply)
            return reply
        raw = entry["raw"]
        del pending_intents[user.id]
        return await _build_and_reply(db, user, conversation_id, raw, text, on_progress)

    # ── 审批类指令 ──
    m = _APPROVE_RE.match(text)
    if m:
        proposal_id = int(m.group(1))

        def _do_approve():
            return _approve_with_saved_keys(db, user, proposal_id)

        reply = await asyncio.to_thread(_do_approve)
        _save_pair(db, conversation_id, user_msg, reply)
        return reply

    m = _REJECT_RE.match(text)
    if m:
        proposal_id = int(m.group(1))

        def _do_reject():
            from ..models import SkillProposal

            proposal = db.query(SkillProposal).filter_by(id=proposal_id, user_id=user.id).first()
            if proposal is None:
                return f"找不到提案 #{proposal_id}。"
            service.reject_proposal(db, user, proposal)
            return f"好的，已放弃「{proposal.slug or proposal.title}」，现场已清理。"

        reply = await asyncio.to_thread(_do_reject)
        _save_pair(db, conversation_id, user_msg, reply)
        return reply

    m = _KEY_RE.match(text)
    if m:
        proposal_id, key_name, key_value = int(m.group(1)), m.group(2), m.group(3)

        def _do_key():
            from ..models import LearnKey, SkillProposal

            proposal = db.query(SkillProposal).filter_by(id=proposal_id, user_id=user.id).first()
            if proposal is None:
                return f"找不到提案 #{proposal_id}。"
            required = json.loads(proposal.required_keys or "{}")
            if key_name not in required:
                return f"提案 #{proposal_id} 不需要 {key_name}，需要的是：{'、'.join(required) or '（无）'}"
            service.os_setenv(key_name, key_value)
            row = db.query(LearnKey).filter_by(user_id=user.id, key_name=key_name).first()
            if row:
                row.value = key_value
            else:
                db.add(LearnKey(user_id=user.id, key_name=key_name, value=key_value))
            db.commit()
            missing = [k for k in required if not service.os_env_has(k)]
            if missing:
                return f"{key_name} 已记录。还缺：{'、'.join(missing)}"
            return f"{key_name} 已记录，密钥齐了。发送「批准 {proposal_id}」上线。"

        reply = await asyncio.to_thread(_do_key)
        _save_pair(db, conversation_id, user_msg, reply)
        return reply

    # ── 学习触发：先纠错并请用户确认，不直接构建 ──
    if not _ACQUIRE_RE.search(text):
        return None

    cfg = _llm_cfg(db, user)
    corrected = await correct_asr_text(text, cfg)

    # 复用检查：技能库里已有高度相似的 → 不重建，直接告诉用户「这个我已经会了」
    from . import retrieval

    similar = await retrieval.search_similar(db, user.id, corrected, cfg, top_k=1)
    if similar and similar[0]["score"] >= 0.86:
        top = similar[0]
        pending_intents[user.id] = {"raw": text.strip(), "ts": time.time(), "kind": "offer_reuse", "offer": top}
        reply = (f"这个我已经会了：{top['description']}（相似度 {int(top['score']*100)}%）。\n"
                 f"直接对我说需求就能用它；想升级它就回复「升级」+ 新的需求描述；说「取消」忽略。")
        _save_pair(db, conversation_id, user_msg, reply)
        return reply

    pending_intents[user.id] = {"raw": corrected, "ts": time.time(), "kind": "confirm"}
    reply = _confirm_prompt(corrected)
    _save_pair(db, conversation_id, user_msg, reply)
    return reply


async def _build_and_reply(db, user: User, conversation_id: int, raw: str, confirm_msg: str, on_progress) -> str:
    """确认后的完整构建：发进度 → 构建 → 回提案文本。"""
    for stage in _PROGRESS_STAGES:
        if on_progress:
            on_progress(stage)
    proposal = await asyncio.to_thread(service.build_proposal, db, user, raw, _llm_cfg(db, user))
    if on_progress:
        on_progress(_PROGRESS_DONE)
    reply = _proposal_reply(proposal)
    _save_pair(db, conversation_id, confirm_msg, reply)
    return reply


def _approve_with_saved_keys(db, user: User, proposal_id: int) -> str:
    """批准时从 LearnKey/环境里收集该提案需要的 key。"""
    import os

    from ..models import LearnKey, SkillProposal

    proposal = db.query(SkillProposal).filter_by(id=proposal_id, user_id=user.id).first()
    if proposal is None:
        return f"找不到提案 #{proposal_id}。"
    required = json.loads(proposal.required_keys or "{}")
    keys = {name: os.environ[name] for name in required if os.environ.get(name)}
    result = service.approve_proposal(db, user, proposal, keys)
    if not result.get("ok"):
        missing = result.get("missing_keys", {})
        lines = ["还差这些密钥才能上线："]
        for name, desc in missing.items():
            lines.append(f"  · {name}（{desc}）→ 发送「key {proposal_id} {name}=你的密钥」")
        return "\n".join(lines)
    return f"学会了！「{result.get('tool_name', proposal.slug)}」已合并上线，现在就能用。"
