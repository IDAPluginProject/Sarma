"""Built-in web search tool."""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from typing import Any


def build_web_search_tool() -> Any:
    """Build the built-in LangChain web search tool."""
    from langchain_core.tools import tool

    @tool("web_search")
    def web_search(query: str, max_results: int = 5, timeout: float = 10.0) -> str:
        """Search the public web and return compact result titles, URLs, and snippets.

        Args:
            query: Search query.
            max_results: Maximum number of results to return.
            timeout: Network timeout in seconds.
        """
        return search_web(query, max_results=max_results, timeout=timeout)

    return web_search


def search_web(query: str, *, max_results: int = 5, timeout: float = 10.0) -> str:
    query = query.strip()
    if not query:
        return "web_search requires a non-empty query."
    limit = max(1, min(int(max_results or 5), 10))
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 Sarma/0.1 "
                "(compatible; local research agent)"
            )
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, float(timeout))) as response:
            body = response.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        return f"web_search failed: {exc}"

    results = _parse_duckduckgo_html(body, limit)
    if not results:
        return "web_search found no results."
    lines = ["Web search results:"]
    for index, item in enumerate(results, start=1):
        lines.append(
            f"\n[{index}] {item['title']}\nURL: {item['url']}\n{item['snippet']}"
        )
    return "\n".join(lines)


def _parse_duckduckgo_html(body: str, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    blocks = re.findall(
        r'<div[^>]+class="result[^"]*"[^>]*>(.*?)</div>\s*</div>',
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for block in blocks:
        title_match = re.search(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not title_match:
            continue
        snippet_match = re.search(
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        result = {
            "title": _clean_html(title_match.group(2)),
            "url": _clean_url(title_match.group(1)),
            "snippet": _clean_html(snippet_match.group(1)) if snippet_match else "",
        }
        if result["title"] and result["url"]:
            results.append(result)
        if len(results) >= limit:
            break
    return results


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return " ".join(text.split())


def _clean_url(value: str) -> str:
    url = html.unescape(value)
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return query["uddg"][0]
    return url
