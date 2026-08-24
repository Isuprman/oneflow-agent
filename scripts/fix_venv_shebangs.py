"""修复 venv 迁移后控制台脚本失效的 shebang（一次性维护工具）。"""
from pathlib import Path

BIN = Path.home() / "work/AiAgentItem/oneflow-agent/.venv/bin"
OLD = "/Users/llinlianghong/work/oneflow-agent"
NEW = "/Users/llinlianghong/work/AiAgentItem/oneflow-agent"

fixed = []
for script in BIN.iterdir():
    if not script.is_file() or script.suffix:
        continue
    try:
        head = script.read_text(encoding="utf-8")[:200]
    except (UnicodeDecodeError, PermissionError):
        continue
    if OLD in head:
        text = script.read_text(encoding="utf-8")
        script.write_text(text.replace(OLD, NEW), encoding="utf-8")
        fixed.append(script.name)

print("fixed:", fixed or "无需要修复的")
