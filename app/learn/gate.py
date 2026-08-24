# 学习门禁 — 生成代码的静态安全检查 + 必需 key 提取
# 原则：门禁是底线不是全部；最终防线是 L2 人工批准。
import ast
import re

# 工具代码禁止出现的危险面（MVP 黑名单，后续可加白名单机制）
FORBIDDEN_PATTERNS = (
    "eval(", "exec(", "__import__", "subprocess", "os.system", "os.popen",
    "pickle", "shutil.rmtree", "os.remove", "os.unlink", "os.rmdir",
    "socket.socket", "open(", "Path(", "importlib",
)

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def check_slug(slug: str) -> str | None:
    """合法 slug 返回 None，否则返回错误说明。"""
    if not SLUG_RE.match(slug or ""):
        return "slug 需为 2~32 位小写字母/数字/下划线且字母开头"
    return None


def static_gate(tool_code: str, test_code: str) -> tuple[list[str], list[str]]:
    """静态检查。返回 (errors, warnings)。errors 非空 = 一票否决。"""
    errors: list[str] = []
    warnings: list[str] = []

    if len(tool_code) > 12000:
        errors.append("工具代码超过 12KB 上限")
    for pat in FORBIDDEN_PATTERNS:
        if pat in tool_code:
            errors.append(f"工具代码包含被禁止的模式: {pat}")

    try:
        tree = ast.parse(tool_code)
    except SyntaxError as e:
        errors.append(f"工具代码语法错误: {e}")
        return errors, warnings

    tool_decorated = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                text = ast.unparse(dec)
                if text.startswith("tool("):
                    tool_decorated += 1
    if tool_decorated != 1:
        errors.append(f"必须恰好定义一个 @tool 函数（当前 {tool_decorated} 个）")

    try:
        ast.parse(test_code)
    except SyntaxError as e:
        errors.append(f"测试代码语法错误: {e}")
    if "def test_" not in test_code and "assert " not in test_code:
        errors.append("测试代码里没有任何测试断言")
    return errors, warnings


def extract_required_keys(tool_code: str) -> dict[str, str]:
    """提取模块级 REQUIRED_KEYS = {"ENV名": "说明"}；同时兜底扫 os.environ/getenv 引用。"""
    keys: dict[str, str] = {}
    try:
        tree = ast.parse(tool_code)
    except SyntaxError:
        return keys
    for node in tree.body:  # 仅模块级
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "REQUIRED_KEYS" for t in node.targets
        ):
            if isinstance(node.value, ast.Dict):
                for k, v in zip(node.value.keys, node.value.values):
                    if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                        keys[str(k.value)] = str(v.value)
    for m in re.finditer(r'os\.(?:environ\[["\'](\w+)["\']|getenv\(["\'](\w+))', tool_code):
        name = m.group(1) or m.group(2)
        keys.setdefault(name, "代码中引用的环境变量")
    return {k: v for k, v in keys.items() if not k.startswith(("LLM_", "ONEFLOW_"))}


def extract_tool_name(tool_code: str) -> str | None:
    m = re.search(r'@tool\(\s*name\s*=\s*["\']([\w-]+)["\']', tool_code)
    if m:
        return m.group(1)
    m = re.search(r'@tool\(\s*["\']([\w-]+)["\']', tool_code)
    return m.group(1) if m else None
