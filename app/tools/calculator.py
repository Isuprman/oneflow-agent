# calculate — 安全表达式求值（ast 白名单，仅标准库，无 eval 危险面）
import ast

from .registry import tool

# 允许的二元/一元/比较运算
_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.FloorDiv, ast.Mod)
_ALLOWED_UNARYOPS = (ast.USub, ast.UAdd)
_ALLOWED_COMPARE_OPS = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)
# Name 仅允许这三个字面量
_ALLOWED_NAMES = {"True": True, "False": False, "None": None}
# 允许的字面量类型
_ALLOWED_CONST = (int, float, bool, str, type(None))


def _check(node):
    if isinstance(node, ast.Expression):
        return _check(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, _ALLOWED_CONST):
        return node
    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
        _check(node.left)
        _check(node.right)
        return node
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARYOPS):
        _check(node.operand)
        return node
    if isinstance(node, ast.Compare):
        _check(node.left)
        for comparator in node.comparators:
            _check(comparator)
        if not all(isinstance(op, _ALLOWED_COMPARE_OPS) for op in node.ops):
            raise ValueError
        return node
    if isinstance(node, ast.Name) and node.id in _ALLOWED_NAMES:
        return node
    raise ValueError


@tool(
    name="calculate",
    description="安全计算数学表达式（四则运算、幂、取模、数字比较）",
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "数学表达式，如 (2+3)*4"},
        },
        "required": ["expression"],
    },
)
def calculate(args, user, db):
    expr = args.get("expression")
    if not expr:
        return {"success": False, "error": "缺少表达式"}
    try:
        tree = ast.parse(str(expr), mode="eval")
        _check(tree)
    except (SyntaxError, ValueError):
        return {"success": False, "error": "不支持的表达式"}
    try:
        result = eval(compile(tree, "<string>", "eval"), {"__builtins__": {}}, _ALLOWED_NAMES)
    except Exception as e:
        return {"success": False, "error": f"计算失败: {e}"}
    return {"success": True, "expression": expr, "result": result}
