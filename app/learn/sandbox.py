# 沙箱 — 在隔离子进程中对候选工具跑 pytest
# MVP 用「临时目录 + 净化环境变量 + 硬超时」；升级路径：Docker 容器内执行。
#
# 约定：临时目录注入 conftest.py，提供 `candidate` 夹具（已加载候选工具模块）。
# 生成代码保持其真实形态（from app.tools.registry import tool），
# 通过 PYTHONPATH 指向项目根保证导入成立；注册副作用随子进程销毁，不污染主进程。
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL_TIMEOUT_SECONDS = 90
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


def run_tests(tool_code: str, test_code: str, slug: str = "cand") -> tuple[bool, str]:
    """在临时目录中执行候选工具的测试。返回 (passed, 输出摘要)。"""
    project_root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix=f"oneflow_learn_{slug}_") as td:
        tdp = Path(td)
        (tdp / "conftest.py").write_text(_CONFTEST, encoding="utf-8")
        (tdp / f"test_{slug}.py").write_text(test_code, encoding="utf-8")
        (tdp / "candidate_tool.py").write_text(tool_code, encoding="utf-8")

        env = {
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": td,
            "LANG": "en_US.UTF-8",
            "PROJECT_ROOT": str(project_root),
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
            output = (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            return False, f"测试超时（>{TOOL_TIMEOUT_SECONDS}s），已终止"
        except Exception as e:
            return False, f"沙箱启动失败: {e}"
    passed = proc.returncode == 0
    return passed, output[-_MAX_OUTPUT:]
