"""Web search module — lightweight, no external dependencies.

Uses DuckDuckGo HTML (html.duckduckgo.com) which is server-rendered,
no JavaScript required. Pure Python stdlib (urllib + html.parser).
"""

import json
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

SEARCH_URL = "https://html.duckduckgo.com/html/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 15


class SearchResult:
    """A single web search result."""

    def __init__(self, title: str = "", url: str = "", snippet: str = ""):
        self.title = title
        self.url = url
        self.snippet = snippet

    def to_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


class _DuckDuckGoHTMLParser(HTMLParser):
    """Parse DuckDuckGo HTML search results into SearchResult objects."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[SearchResult] = []
        self._current: SearchResult | None = None
        self._in_result = False
        self._in_title = False
        self._in_snippet = False
        self._in_url = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = self._classes(attrs)

        # Each result is a div with class "result"
        if tag == "div" and "result" in classes:
            self._current = SearchResult()
            self._in_result = True
            return

        if not self._in_result:
            return

        # Title link: <a class="result__a" href="...">
        if tag == "a" and "result__a" in classes:
            self._in_title = True
            href = dict(attrs).get("href", "")
            if href and self._current:
                self._current.url = href
            return

        # Snippet link: <a class="result__snippet" href="...">
        if tag == "a" and "result__snippet" in classes:
            self._in_snippet = True
            return

        # URL display: <a class="result__url" href="...">
        if tag == "a" and "result__url" in classes:
            self._in_url = True
            return

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._in_result:
            if self._current and (self._current.title or self._current.snippet):
                self.results.append(self._current)
            self._current = None
            self._in_result = False
            self._in_title = False
            self._in_snippet = False
            self._in_url = False
            return

        if tag == "a" and self._in_title:
            self._in_title = False
            return
        if tag == "a" and self._in_snippet:
            self._in_snippet = False
            return
        if tag == "a" and self._in_url:
            self._in_url = False
            return

    def handle_data(self, data: str) -> None:
        if not self._in_result or not self._current:
            return
        data = data.strip()
        if not data:
            return
        if self._in_title:
            self._current.title += data
        elif self._in_snippet:
            if self._current.snippet:
                self._current.snippet += " "
            self._current.snippet += data
        elif self._in_url:
            if not self._current.url:
                self._current.url = data

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
        for k, v in attrs:
            if k == "class" and v:
                return set(v.split())
        return set()


def search_web(query: str, count: int = 5) -> dict[str, Any]:
    """Search the web using DuckDuckGo HTML mode.

    Args:
        query: The search query string.
        count: Maximum number of results to return (default 5, max 20).

    Returns:
        dict with keys:
          - query (str): original query
          - results (list[dict]): [{title, url, snippet}, ...]
          - count (int): number of results
          - error (str, optional): error message if search failed
    """
    params = urllib.parse.urlencode({"q": query})
    url = f"{SEARCH_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"query": query, "results": [], "count": 0, "error": str(e)}

    parser = _DuckDuckGoHTMLParser()
    parser.feed(html)

    results = [r.to_dict() for r in parser.results[:count]]
    return {"query": query, "results": results, "count": len(results)}


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "hello world"
    result = search_web(q, count=5)
    print(json.dumps(result, ensure_ascii=False, indent=2))
