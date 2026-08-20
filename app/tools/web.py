# 联网工具 — web_search（DuckDuckGo，免费无 Key）+ read_webpage（抓正文）
import re

import httpx

from .registry import tool

MAX_PAGE_CHARS = 4000
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) OneFlowAgent/1.0"


def html_to_text(html: str, limit: int = MAX_PAGE_CHARS) -> str:
    """从 HTML 提取可读正文（纯函数，便于测试）：去脚本样式、压空白、截断。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "iframe"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    if len(cleaned) > limit:
        cleaned = cleaned[:limit] + "\n…（正文过长已截断）"
    return cleaned


@tool(
    name="web_search",
    description="联网搜索（DuckDuckGo，免费无 Key）：查询新闻、资讯、实时信息。返回标题/链接/摘要列表；"
    "需要详细内容时再用 read_webpage 读取具体网页。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "max_results": {"type": "integer", "description": "返回条数，默认5，最多10"},
        },
        "required": ["query"],
    },
)
def web_search(args, user, db):
    query = (args.get("query") or "").strip()
    if not query:
        return {"success": False, "error": "搜索关键词不能为空"}
    max_results = min(int(args.get("max_results") or 5), 10)

    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        return {"success": False, "error": f"搜索失败: {e}"}

    results = [
        {"title": r.get("title") or "", "url": r.get("href") or "", "snippet": r.get("body") or ""}
        for r in raw
    ]
    if not results:
        return {"success": True, "results": [], "note": "没有搜到相关内容，换个关键词试试"}
    return {"success": True, "results": results}


@tool(
    name="read_webpage",
    description="读取指定 URL 网页的正文文本（自动去广告/导航，超长截断）。配合 web_search 深入阅读某条结果。",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "完整网页地址，http(s):// 开头"}},
        "required": ["url"],
    },
)
def read_webpage(args, user, db):
    url = (args.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return {"success": False, "error": "url 必须以 http:// 或 https:// 开头"}

    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": _UA})
        resp.raise_for_status()
    except Exception as e:
        return {"success": False, "error": f"网页读取失败: {e}"}

    text = html_to_text(resp.text)
    if not text.strip():
        return {"success": False, "error": "该网页没有可提取的正文（可能是纯图片/JS 渲染页面）"}
    return {"success": True, "url": url, "content": text}
