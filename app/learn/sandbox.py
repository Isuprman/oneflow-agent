# 沙箱 — 对候选工具跑 pytest，两种隔离级别：
#   docker     容器内执行（无网络、文件系统只读挂载），首选
#   subprocess 临时目录 + 净化环境变量 + 硬超时（本机兜底）
# 模式由环境变量 LEARN_SANDBOX 控制：auto(默认，docker 可用则用)/docker/subprocess。
# Docker 首次使用会自动构建 oneflow-learn-runner 镜像（项目依赖 + pytest）。
#
# 注意：docker CLI 卡死时子进程会占住管道导致 communicate 永等，
# 所以所有外部命令统一走 _run_cmd（新进程组 + 超时整组 SIGKILL）。
import os
import signal
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

TOOL_TIMEOUT_SECONDS = 120
_MAX_OUTPUT = 6000


def _run_cmd(cmd: list[str], timeout: int, cwd=None, env=None) -> tuple[int, str]:
    """执行外部命令；超时对整个进程组 SIGKILL，返回 (code, 输出)。"""
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, (out or "")
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            out, _ = proc.communicate(timeout=5)
        except Exception:
            out = ""
        return 124, (out or "") + f"\n[命令超时({timeout}s)已终止: {' '.join(cmd[:3])}...]"

_CONFTEST = """\
import importlib.util, os, sys, pytest

sys.path.insert(0, os.environ["PROJECT_ROOT"])

@pytest.fixture()
def candidate():
    spec = importlib.util.spec_from_file_location("candidate_tool", os.environ["CANDIDATE_TOOL"])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
"""

_RUNNER_IMAGE = "oneflow-learn-runner:latest"
_RUNNER_DOCKERFILE = """\
FROM python:3.12-slim
WORKDIR /sandbox
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} -r /tmp/requirements.txt pytest
"""

_project_root = Path(__file__).resolve().parents[2]
_docker_ok: bool | None = None  # 进程内缓存探测结果


def _mode() -> str:
    mode = os.environ.get("LEARN_SANDBOX", "auto").lower()
    if mode in ("docker", "subprocess"):
        return mode
    return "docker" if _docker_available() else "subprocess"


def _docker_available() -> bool:
    """守护进程在线 且 真能拉到镜像（国内镜像源常整体失联，只看 info 会误判）。"""
    global _docker_ok
    if _docker_ok is None:
        code, _ = _run_cmd(["docker", "info", "--format", "ok"], timeout=10)
        if code != 0:
            _docker_ok = False
            return False
        code, _ = _run_cmd(["docker", "pull", "hello-world:latest"], timeout=60)
        _docker_ok = code == 0
    return _docker_ok


def _ensure_runner_image() -> None:
    code, output = _run_cmd(["docker", "image", "inspect", _RUNNER_IMAGE], timeout=20)
    if code == 0:
        return
    import tempfile as _tf

    with _tf.TemporaryDirectory() as bd:
        ctx = Path(bd)
        (ctx / "Dockerfile").write_text(_RUNNER_DOCKERFILE, encoding="utf-8")
        reqs = _project_root / "requirements.txt"
        if reqs.exists():
            (ctx / "requirements.txt").write_text(reqs.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            (ctx / "requirements.txt").write_text("", encoding="utf-8")
        code, output = _run_cmd(
            ["docker", "build", "-t", _RUNNER_IMAGE, "."],
            timeout=1200, cwd=ctx,
        )
        if code != 0:
            raise RuntimeError(f"runner 镜像构建失败: {output[-400:]}")


def _run_docker(tdp: Path, slug: str) -> tuple[int, str]:
    _ensure_runner_image()
    name = f"oneflow-learn-{slug}-{uuid.uuid4().hex[:8]}"
    cmd = [
        "docker", "run", "--rm", "--name", name,
        "--network", "none",
        "-v", f"{tdp}:/sandbox",
        "-v", f"{_project_root}:/app_src:ro",
        "-e", "PROJECT_ROOT=/app_src",
        "-e", "CANDIDATE_TOOL=/sandbox/candidate_tool.py",
        "-w", "/sandbox",
        _RUNNER_IMAGE,
        "python3", "-m", "pytest", "-q", f"test_{slug}.py", "--no-header", "-x",
    ]
    code, output = _run_cmd(cmd, timeout=TOOL_TIMEOUT_SECONDS)
    if code == 124:
        _run_cmd(["docker", "kill", name], timeout=20)
    return code, output


def run_tests(tool_code: str, test_code: str, slug: str = "cand") -> tuple[bool, str]:
    """对候选工具执行测试。返回 (passed, 输出摘要)。"""
    docker_note = ""
    if _mode() == "docker":
        try:
            with tempfile.TemporaryDirectory(prefix=f"oneflow_learn_{slug}_") as td:
                tdp = Path(td)
                _write_fixtures(tdp, tool_code, test_code, slug)
                code, output = _run_docker(tdp, slug)
            return code == 0, output[-_MAX_OUTPUT:]
        except Exception as e:  # 镜像缺失/守护进程异常 → 回退本机沙箱
            docker_note = f"[docker 不可用({e})，本次回退子进程沙箱]\n"

    with tempfile.TemporaryDirectory(prefix=f"oneflow_learn_{slug}_") as td:
        tdp = Path(td)
        _write_fixtures(tdp, tool_code, test_code, slug)
        env = {
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": td,
            "LANG": "en_US.UTF-8",
            "PROJECT_ROOT": str(_project_root),
            "CANDIDATE_TOOL": str(tdp / "candidate_tool.py"),
        }
        code, output = _run_cmd(
            [sys.executable, "-m", "pytest", "-q", f"test_{slug}.py", "--no-header", "-x"],
            timeout=TOOL_TIMEOUT_SECONDS,
            cwd=td,
            env=env,
        )
    passed = code == 0
    if code == 124 and not docker_note:
        return False, f"测试超时（>{TOOL_TIMEOUT_SECONDS}s），已终止"
    return passed, (docker_note + output)[-_MAX_OUTPUT:]


def _write_fixtures(tdp: Path, tool_code: str, test_code: str, slug: str) -> None:
    (tdp / "conftest.py").write_text(_CONFTEST, encoding="utf-8")
    (tdp / f"test_{slug}.py").write_text(test_code, encoding="utf-8")
    (tdp / "candidate_tool.py").write_text(tool_code, encoding="utf-8")
