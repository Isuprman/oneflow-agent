# OneFlow 后台职责注册表 — 每个主动服务一个 job 模块，tick 只做遍历调度。
# 契约：async run(db, now)；hour_gate=None 表示每次 tick 都跑；label 用于失败自报文案。
# 加新后台职责：新建 jobs/<name>.py 并在 REGISTRY 追加一项，不改 scheduler.tick。
from dataclasses import dataclass
from typing import Callable

from . import away, checkups, care, habit_proposals, habits, interviews, reminders, skill_quality


@dataclass(frozen=True)
class Job:
    label: str  # 失败自报文案前缀，如 "日程提醒检查失败（…）"
    hour_gate: int | None  # 仅在该小时及之后运行；None = 每 tick
    run: Callable[[object, object], object]  # async (db, now) -> None


REGISTRY: list[Job] = [
    Job(label="日程提醒检查", hour_gate=None, run=reminders.run),
    Job(label="数字分身检查", hour_gate=None, run=away.run),
    Job(label="情景关怀检查", hour_gate=care.CARE_HOUR, run=care.run),
    Job(label="习惯洞察", hour_gate=habits.HABIT_INSIGHT_HOUR, run=habits.run),
    Job(label="习惯提案生成", hour_gate=habits.HABIT_INSIGHT_HOUR, run=habit_proposals.run),
    Job(label="技能质量检查", hour_gate=habits.HABIT_INSIGHT_HOUR, run=skill_quality.run),
    Job(label="反向面试", hour_gate=habits.HABIT_INSIGHT_HOUR, run=interviews.run),
    Job(label="年度体检", hour_gate=habits.HABIT_INSIGHT_HOUR, run=checkups.run),
]
