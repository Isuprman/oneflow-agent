# calculate 测试 — 正常计算 + 危险表达式拒绝
import pytest

from app.tools.calculator import calculate


def test_basic_arithmetic():
    result = calculate({"expression": "(2+3)*4"}, None, None)
    assert result["success"] is True
    assert result["result"] == 20


def test_power():
    result = calculate({"expression": "2**10"}, None, None)
    assert result["success"] is True
    assert result["result"] == 1024


def test_mod_and_compare():
    assert calculate({"expression": "7 % 3"}, None, None)["result"] == 1
    assert calculate({"expression": "3 > 2"}, None, None)["result"] is True


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os')",
        "[].__class__",
        "'x'.__class__",
        "open('/etc/passwd')",
        "__builtins__['exit']",
    ],
)
def test_dangerous_expressions_rejected(expr):
    result = calculate({"expression": expr}, None, None)
    assert result["success"] is False


def test_missing_expression():
    result = calculate({}, None, None)
    assert result["success"] is False
