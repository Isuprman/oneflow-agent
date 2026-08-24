# 学习服务编排 — 构建→提案→批准合并→热激活 的完整状态机
#
# 分支策略（用户要求：可回退）：
#   构建阶段在 git worktree（/tmp 下）的 skill/<slug> 分支上提交，主工作区不受扰动；
#   批准 = 主仓 merge --no-ff（一个合并提交，revert 即整体回退）；
#   拒绝 = 删分支清 worktree，零残留。
import json
import logging
import shutil
import subprocess
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import SkillProposal, User
from . import gate

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class LearnError(Exception):
    pass


def _git(args: list[str], cwd: Path | str | None = None) -> str:
    """cwd 缺省时取「当时的」PROJECT_ROOT（调用时解析，测试可整体重定向）。"""
    if cwd is None:
        cwd = PROJECT_ROOT
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise LearnError(f"git {' '.join(args)} 失败: {proc.stderr.strip()[:300]}")
    return proc.stdout.strip()


def _worktree_dir(branch: str) -> Path:
    return Path("/tmp") / f"oneflow_skill_wt_{uuid.uuid4().hex[:8]}"


def _current_branch() -> str:
    return _git(["rev-parse", "--abbrev-ref", "HEAD"])


def commit_candidate(slug: str, tool_code: str, test_code: str) -> str:
    """把候选代码提交到独立 worktree 的 skill/<slug> 分支，返回分支名。不动主工作区。"""
    branch = f"skill/{slug}"
    wt = _worktree_dir(branch)
    _git(["worktree", "add", "-B", branch, str(wt)])
    try:
        wt_skills = wt / "app" / "tools" / "skills"
        wt_tests = wt / "tests" / "skills"
        wt_skills.mkdir(parents=True, exist_ok=True)
        wt_tests.mkdir(parents=True, exist_ok=True)
        (wt_skills / f"{slug}.py").write_text(tool_code, encoding="utf-8")
        (wt_tests / f"test_{slug}.py").write_text(test_code, encoding="utf-8")
        _git(["add", f"app/tools/skills/{slug}.py", f"tests/skills/test_{slug}.py"], cwd=wt)
        _git(["-c", "user.name=oneflow-learner", "-c", "user.email=learner@oneflow.local",
              "commit", "-m", f"learn: 新技能 {slug}（候选）"], cwd=wt)
    except Exception:
        shutil.rmtree(wt, ignore_errors=True)
        _git(["worktree", "prune"])
        raise
    return branch


def discard_branch(branch: str) -> None:
    """清 worktree 挂载点并强删分支；尽力而为，失败只记日志。"""
    try:
        out = _git(["worktree", "list", "--porcelain"])
        mounts = [l.split(" ", 1)[1] for l in out.splitlines() if l.startswith("worktree ")]
        for m in mounts:
            if "/oneflow_skill_wt_" in m:
                shutil.rmtree(m, ignore_errors=True)
        _git(["worktree", "prune"])
    except Exception as e:
        logger.warning("清理 worktree 异常: %s", e)
    try:
        _git(["branch", "-D", branch])
    except Exception as e:
        logger.warning("删除分支 %s 异常: %s", branch, e)


def merge_and_activate(slug: str, branch: str) -> dict:
    """主仓合并技能分支并热加载。返回激活信息。

    激活采用「按文件路径加载并顶替 sys.modules」而非包发现式 import——
    无论合并落在哪个工作区路径都能生效，升级时天然覆盖旧版本。
    """
    _git(["merge", "--no-ff", branch, "-m", f"merge: 自学习技能 {slug} 上线"])
    import importlib.util
    import sys

    file_path = PROJECT_ROOT / "app" / "tools" / "skills" / f"{slug}.py"
    name = f"app.tools.skills.{slug}"
    spec = importlib.util.spec_from_file_location(name, file_path)
    if spec is None or spec.loader is None:
        raise LearnError(f"无法为 {file_path} 构建加载器")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)

    tool_name = gate.extract_tool_name(file_path.read_text(encoding="utf-8"))
    from ..tools.registry import _REGISTRY

    live = bool(tool_name) and tool_name in _REGISTRY
    return {"tool_name": tool_name, "live": live}


def build_proposal(db: Session, user: User, request_text: str, cfg: dict | None) -> SkillProposal:
    """完整构建流程：LLM 生成→门禁→沙箱→分支提交→pending 提案。"""
    from .builder import build_with_repair
    from .sandbox import run_tests

    log: list[str] = []
    base_status = "pending"
    tool_code: str | None = None
    test_code: str | None = None

    def _save(p: SkillProposal) -> SkillProposal:
        db.add(p)
        db.commit()
        db.refresh(p)
        return p

    try:
        import asyncio

        tool_code, test_code, build_log = asyncio.run(build_with_repair(request_text, cfg, run_tests))
        log.extend(build_log)
    except Exception as e:
        log.append(f"构建异常: {e}")

    if not tool_code or not test_code:
        return _save(SkillProposal(
            user_id=user.id, slug="", title=request_text[:120], description=request_text,
            status="failed", tool_code="", test_code="",
            test_output="\n".join(log)[-4000:], required_keys="{}", branch="",
        ))

    raw_name = gate.extract_tool_name(tool_code) or ""
    slug = raw_name.replace("-", "_").lower()
    slug_err = gate.check_slug(slug)
    if slug_err:
        slug = "skill_" + uuid.uuid4().hex[:6]
        log.append(f"工具名不合规（{slug_err}），改用随机 slug: {slug}")
    elif (PROJECT_ROOT / "app/tools/skills" / f"{slug}.py").exists():
        log.append(f"技能 {slug} 已存在，本次为升级替换")

    branch = ""
    try:
        branch = commit_candidate(slug, tool_code, test_code)
        log.append(f"候选已提交到分支 {branch}")
    except Exception as e:
        return _save(SkillProposal(
            user_id=user.id, slug=slug, title=raw_name or request_text[:80],
            description=request_text, status="failed", tool_code=tool_code, test_code=test_code,
            test_output=("\n".join(log) + f"\n分支提交失败: {e}")[-4000:],
            required_keys="{}", branch="",
        ))

    return _save(SkillProposal(
        user_id=user.id, slug=slug, title=raw_name or slug,
        description=request_text, status=base_status,
        tool_code=tool_code, test_code=test_code,
        test_output="\n".join(log)[-4000:],
        required_keys=json.dumps(gate.extract_required_keys(tool_code), ensure_ascii=False),
        branch=branch,
    ))


def approve_proposal(db: Session, user: User, proposal: SkillProposal, keys: dict[str, str]) -> dict:
    """批准：校验 key → 合并 → 热激活 → 记录 key。"""
    if proposal.status != "pending":
        raise LearnError(f"提案状态为 {proposal.status}，只有 pending 可批准")
    if proposal.user_id != user.id:
        raise LearnError("只能操作自己的提案")

    required = json.loads(proposal.required_keys or "{}")
    missing = [k for k in required if k not in keys and not os_env_has(k)]
    if missing:
        return {"ok": False, "missing_keys": {k: required[k] for k in missing}}

    from ..models import LearnKey

    for name, value in keys.items():
        os_setenv(name, value)
        row = db.query(LearnKey).filter_by(user_id=user.id, key_name=name).first()
        if row:
            row.value = value
        else:
            db.add(LearnKey(user_id=user.id, key_name=name, value=value))
    db.commit()

    info = merge_and_activate(proposal.slug, proposal.branch)
    proposal.status = "approved"
    db.commit()
    return {"ok": True, **info}


def reject_proposal(db: Session, user: User, proposal: SkillProposal) -> None:
    if proposal.user_id != user.id:
        raise LearnError("只能操作自己的提案")
    if proposal.branch:
        discard_branch(proposal.branch)
    proposal.status = "rejected"
    db.commit()


def os_env_has(name: str) -> bool:
    import os

    return bool(os.environ.get(name))


def os_setenv(name: str, value: str) -> None:
    import os

    os.environ[name] = value


def inject_saved_keys(db: Session) -> int:
    """启动时把用户已保存的工具 key 注入进程环境。"""
    from ..models import LearnKey

    n = 0
    for row in db.query(LearnKey).all():
        os_setenv(row.key_name, row.value)
        n += 1
    return n
