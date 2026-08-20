# 联网工具测试 — 正文提取纯函数 + 参数校验（不真实发网络请求）
from app.tools.registry import execute
from app.tools.web import html_to_text

SAMPLE_HTML = """
<html><head><style>body{color:red}</style><script>var x=1;</script></head>
<body>
<nav>导航栏</nav>
<article><h1>标题一</h1><p>第一段正文内容。</p><p>第二段正文内容。</p></article>
<footer>页脚</footer>
</body></html>
"""


def test_html_to_text_strips_noise():
    text = html_to_text(SAMPLE_HTML)
    assert "标题一" in text and "第一段正文内容。" in text
    assert "var x=1" not in text          # script 去除
    assert "color:red" not in text        # style 去除
    assert "导航栏" not in text            # nav 去除
    assert "页脚" not in text              # footer 去除


def test_html_to_text_truncates():
    long_html = "<p>" + "长" * 6000 + "</p>"
    text = html_to_text(long_html, limit=4000)
    assert len(text) <= 4000 + 30
    assert "已截断" in text


def test_read_webpage_rejects_bad_url():
    result = execute("read_webpage", {"url": "ftp://x"}, None, None)
    assert result["success"] is False
    assert "http" in result["error"]


def test_web_search_requires_query():
    result = execute("web_search", {"query": "  "}, None, None)
    assert result["success"] is False
    assert "不能为空" in result["error"]


def test_web_search_mocked(monkeypatch):
    """mock DDGS 客户端：验证结果字段映射。"""

    class FakeDDGS:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def text(self, query, max_results=5):
            return [
                {"title": "结果一", "href": "https://a.example.com", "body": "摘要一"},
                {"title": "结果二", "href": "https://b.example.com", "body": "摘要二"},
            ]

    import app.tools.web as web_mod

    class FakeModule:
        DDGS = FakeDDGS

    monkeypatch.setitem(__import__("sys").modules, "ddgs", FakeModule())
    result = web_mod.web_search({"query": "测试"}, None, None)
    assert result["success"] is True
    assert result["results"][0]["title"] == "结果一"
    assert result["results"][0]["url"] == "https://a.example.com"
    assert result["results"][1]["snippet"] == "摘要二"
