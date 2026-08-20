# 注册表测试（允许 mock 的地方）
from app.tools.registry import registry, schemas, execute

EXPECTED_TOOLS = [
    "get_weather",
    "add_expense",
    "query_expense",
    "schedule_event",
    "list_schedule",
    "calculate",
    "search_hotel",
    "create_scheduled_task",
    "list_scheduled_tasks",
    "cancel_scheduled_task",
    "web_search",
    "read_webpage",
]


def test_registry_contains_all_tools():
    for name in EXPECTED_TOOLS:
        assert name in registry
    assert len(registry) >= len(EXPECTED_TOOLS)


def test_schemas_format():
    schemas_list = schemas()
    assert isinstance(schemas_list, list)
    names = [s["function"]["name"] for s in schemas_list]
    for name in EXPECTED_TOOLS:
        assert name in names
    for s in schemas_list:
        assert s["type"] == "function"
        assert "description" in s["function"]
        assert "parameters" in s["function"]


def test_execute_unknown_tool():
    result = execute("no_such_tool", {}, None, None)
    assert result["success"] is False
    assert "未知工具" in result["error"]
