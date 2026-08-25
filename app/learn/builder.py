# Builder — 调 LLM 生成候选工具代码与测试，带「测试失败反馈→修复」循环
import re

from ..agent.llm import chat

MAX_REPAIR_ROUNDS = 2

_SYSTEM = """你是 OneFlow 自学习工具工厂的构建器。根据用户需求，生成一个可独立测试的工具模块和对应 pytest 测试。

硬性契约（违反即报废）：
1. 工具是单文件模块：顶部 `from app.tools.registry import tool`
2. 恰好用 @tool(name=..., description=..., parameters={...}) 注册一个函数
3. 函数签名固定：(args: dict, user, db) -> dict；返回 {"success": True, ...数据} 或 {"success": False, "error": "..."}
4. 只用标准库 + requests/httpx；禁止 eval/exec/subprocess/os.system/open()/文件读写/socket
5. 需要外部 API key 时：模块级声明 REQUIRED_KEYS = {"环境变量名": "中文说明"}，代码里用 os.environ 读
6. 网络请求必须设 timeout=10

输出格式（严格遵守，只输出两个代码块，不要多余解释）：
```tool
<完整工具模块代码>
```
```tests
<pytest 测试代码>
```

测试约定：conftest 已提供 candidate 夹具（加载后的工具模块）。直接写：
def test_xxx(candidate):
    result = candidate.<你的函数名>({...参数...}, None, None)
    assert result["success"] is ...
注意：不要在测试里访问真实外网——把网络调用设计成可用假参触发失败路径，或对纯逻辑断言。
"""

_EXAMPLE = '''参考范例（计算器工具）：
```tool
from app.tools.registry import tool


@tool(
    name="demo_upper",
    description="把英文文本转大写",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string", "description": "原文"}},
        "required": ["text"],
    },
)
def demo_upper(args: dict, user, db) -> dict:
    text = str(args.get("text", ""))
    if not text:
        return {"success": False, "error": "text 不能为空"}
    return {"success": True, "result": text.upper()}
```
```tests
def test_demo_upper(candidate):
    r = candidate.demo_upper({"text": "abc"}, None, None)
    assert r == {"success": True, "result": "ABC"}


def test_demo_upper_empty(candidate):
    assert candidate.demo_upper({"text": ""}, None, None)["success"] is False
```
'''


def _parse_blocks(text: str) -> tuple[str | None, str | None]:
    """从回复中提取 ```tool 与 ```tests 两个代码块。"""
    tm = re.search(r"```tool\s*\n(.*?)```", text, re.S)
    sm = re.search(r"```tests\s*\n(.*?)```", text, re.S)
    tool_code = tm.group(1).strip() if tm else None
    test_code = sm.group(1).strip() if sm else None
    if not tool_code and "```python" in text:  # 兜底：模型没用自定义标记时按 python 块顺序取
        blocks = re.findall(r"```python\s*\n(.*?)```", text, re.S)
        if len(blocks) >= 2:
            tool_code, test_code = blocks[0].strip(), blocks[1].strip()
    return tool_code, test_code


async def build_tool(user_request: str, cfg: dict | None, repair_feedback: str | None = None) -> tuple[str | None, str | None]:
    """单轮生成。repair_feedback 非空时作为修复上下文。返回 (tool_code, test_code)。"""
    parts = ["用户需求：", user_request, "", ""]
    if repair_feedback:
        parts[2] = "上次问题与修复要求："
        parts[3] = repair_feedback
    user_content = "\n".join(parts) + "\n" + _EXAMPLE
    result = await chat(
        messages=[{"role": "system", "content": _SYSTEM},
                  {"role": "user", "content": user_content}],
        tools=[],
        cfg=cfg,
        scene="learn_build",
    )
    if result.error or not result.text:
        return None, None
    return _parse_blocks(result.text)


async def build_with_repair(user_request: str, cfg: dict | None, run_tests) -> tuple[str | None, str | None, list[str]]:
    """生成→静态检查+沙箱→失败带反馈重试。返回 (tool_code|None, test_code|None, 日志列表)。"""
    from . import gate

    log: list[str] = []
    feedback = None
    for attempt in range(MAX_REPAIR_ROUNDS + 1):
        tool_code, test_code = await build_tool(user_request, cfg, feedback)
        if not tool_code or not test_code:
            log.append(f"第{attempt + 1}轮：LLM 未产出有效代码块")
            feedback = "上次没有按格式输出 ```tool 和 ```tests 两个代码块，请严格遵守输出格式。"
            continue
        errors, warnings = gate.static_gate(tool_code, test_code)
        if errors:
            joined = "; ".join(errors)
            log.append(f"第{attempt + 1}轮：静态门禁拦截 — {joined}")
            feedback = "上次的代码触发了安全门禁，必须修复：\n- " + joined.replace("; ", "\n- ") + "\n请重新生成完整两段代码。"
            continue
        passed, output = run_tests(tool_code, test_code)
        if passed:
            tail = f"（警告: {'; '.join(warnings)}）" if warnings else ""
            log.append(f"第{attempt + 1}轮：沙箱测试通过 ✅{tail}")
            return tool_code, test_code, log
        log.append(f"第{attempt + 1}轮：沙箱测试失败 — {output[-500:]}")
        feedback = (
            "上次生成的代码测试未通过，pytest 输出如下：\n" + output[-1500:]
            + "\n请修复后重新输出完整的两段代码。"
        )
    return None, None, log
