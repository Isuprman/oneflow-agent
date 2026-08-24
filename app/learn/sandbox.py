# 沙箱 — 对候选工具跑 pytest，两种隔离级别：
#   docker     容器内执行（无网络、文件系统只读挂载），首选
#   subprocess 临时目录 + 净化环境变量 + 硬超时（本机兜底）
# 模式由环境变量 LEARN_SANDBOX 控制：auto(默认，docker 可用则用)/docker/subprocess。
# Docker 首次使用会自动构建 oneflow-learn-runner 镜像（项目依赖 + pytest）。
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

TOOL_TIMEOUT_SECONDS = 120
_MAX_OUTPUT = 6000

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
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt pytest
"""

_project_root = Path(__file__).resolve().parents[2]
_docker_ok: bool | None = None  # 进程内缓存探测结果


def _mode() -> str:
    mode = os.environ.get("LEARN_SANDBOX", "auto").lower()
    if mode in ("docker", "subprocess"):
        return mode
    return "docker" if _docker_available() else "subprocess"


def _docker_available() -> bool:
    global _docker_ok
    if _docker_ok is None:
        try:
            proc = subprocess.run(["docker", "info", "--format", "ok"],
                                  capture_output=True, text=True, timeout=10)
            _docker_ok = proc.returncode == 0
        except Exception:
            _docker_ok = False
    return _docker_ok


def _ensure_runner_image() -> None:
    check = subprocess.run(["docker", "image", "inspect", _RUNNER_IMAGE],
                           capture_output=True, timeout=15)
    if check.returncode == 0:
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
        build = subprocess.run(
            ["docker", "build", "-t", _RUNNER_IMAGE, "."],
            cwd=ctx, capture_output=True, text=True, timeout=900,
        )
        if build.returncode != 0:
            raise RuntimeError(f"runner 镜像构建失败: {build.stderr[-400:]}")


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
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TOOL_TIMEOUT_SECONDS)
        output = (proc.stdout or "") + (proc.stderr or "")
        code = proc.returncode
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], capture_output=True, timeout=20)
        return 124, f"测试超时（>{TOOL_TIMEOUT_SECONDS}s），容器已终止"
    except Exception as e:
        return 1, f"Docker 启动失败: {e}"
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
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", f"test_{slug}.py", "--no-header", "-x"],
                cwd=td,
                env=env,
                capture_output=True,
                text=True,
                timeout=TOOL_TIMEOUT_SECONDS,
            )
            passed = proc.returncode == 0
            output = (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            return False, f"{docker_note}测试超时（>{TOOL_TIMEOUT_SECONDS}s），已终止"
        except Exception as e:
            return False, f"{docker_note}沙箱启动失败: {e}"
    return passed, (docker_note + output)[-_MAX_OUTPUT:]


def _write_fixtures(tdp: Path, tool_code: str, test_code: str, slug: str) -> None:
    (tdp / "conftest.py").write_text(_CONFTEST, encoding="utf-8")
    (tdp / f"test_{slug}.py").write_text(test_code, encoding="utf-8")
    (tdp / "candidate_tool.py").write_text(tool_code, encoding="utf-8")
