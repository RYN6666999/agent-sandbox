"""Tests for web search module and API endpoints."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


# ── orchestrator/search.py ─────────────────────────────────────────────────


def test_search_parse_real_html():
    """_DuckDuckGoHTMLParser 能正確解析真實的 DuckDuckGo HTML 結構。"""
    from orchestrator.search import _DuckDuckGoHTMLParser

    html = """
    <html><body>
    <div class="results">
      <div class="result">
        <h2 class="result__title">
          <a class="result__a" href="https://example.com">Example Domain</a>
        </h2>
        <a class="result__snippet" href="https://example.com">This domain is for use in illustrative examples.</a>
        <span class="result__url">example.com</span>
      </div>
      <div class="result">
        <h2 class="result__title">
          <a class="result__a" href="https://python.org">Python.org</a>
        </h2>
        <a class="result__snippet" href="https://python.org">The official Python website.</a>
        <span class="result__url">python.org</span>
      </div>
    </div>
    </body></html>
    """

    parser = _DuckDuckGoHTMLParser()
    parser.feed(html)

    assert len(parser.results) == 2
    assert parser.results[0].title == "Example Domain"
    assert parser.results[0].url == "https://example.com"
    assert "illustrative examples" in parser.results[0].snippet
    assert parser.results[1].title == "Python.org"
    assert parser.results[1].url == "https://python.org"


def test_search_parse_empty_html():
    """空 HTML → 空結果。"""
    from orchestrator.search import _DuckDuckGoHTMLParser

    parser = _DuckDuckGoHTMLParser()
    parser.feed("<html></html>")
    assert len(parser.results) == 0


def test_search_parse_no_results_div():
    """沒有 result div → 空結果。"""
    from orchestrator.search import _DuckDuckGoHTMLParser

    parser = _DuckDuckGoHTMLParser()
    parser.feed("<html><body><div class='other'>no results</div></body></html>")
    assert len(parser.results) == 0


@patch("orchestrator.search.urllib.request.urlopen")
def test_search_web_success(mock_urlopen):
    """search_web 回傳正確結構。"""
    from orchestrator.search import search_web

    # Mock HTTP response
    class MockResponse:
        def read(self):
            return b"""
            <html><body>
            <div class="results">
              <div class="result">
                <h2 class="result__title">
                  <a class="result__a" href="https://python.org">Python</a>
                </h2>
                <a class="result__snippet" href="https://python.org">A programming language.</a>
              </div>
            </div>
            </body></html>
            """

        def __exit__(self, *args):
            pass

        def __enter__(self):
            return self

    class MockUrlOpen:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return MockResponse()

        def __exit__(self, *args):
            pass

        def read(self):
            return MockResponse().read()

    mock_urlopen.return_value = MockResponse()

    result = search_web("python", count=5)
    assert result["query"] == "python"
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Python"
    assert result["results"][0]["url"] == "https://python.org"
    assert result["count"] == 1
    assert "error" not in result


@patch("orchestrator.search.urllib.request.urlopen")
def test_search_web_network_error(mock_urlopen):
    """連線錯誤 → 回傳 error + 空結果。"""
    from orchestrator.search import search_web

    mock_urlopen.side_effect = ConnectionError("DNS failed")

    result = search_web("test")
    assert result["query"] == "test"
    assert result["results"] == []
    assert result["count"] == 0
    assert "error" in result


@patch("orchestrator.search.urllib.request.urlopen")
def test_search_web_timeout(mock_urlopen):
    """逾時 → 回傳 error + 空結果。"""
    from orchestrator.search import search_web

    mock_urlopen.side_effect = TimeoutError("timed out")

    result = search_web("test")
    assert result["query"] == "test"
    assert result["results"] == []
    assert result["count"] == 0
    assert "error" in result


@patch("orchestrator.search.urllib.request.urlopen")
def test_search_web_respects_count(mock_urlopen):
    """count 參數限制回傳結果數量。"""
    from orchestrator.search import search_web

    class MockResponse:
        def read(self):
            items = ""
            for i in range(10):
                items += f"""
                <div class="result">
                  <h2 class="result__title">
                    <a class="result__a" href="https://example.com/{i}">Result {i}</a>
                  </h2>
                  <a class="result__snippet" href="https://example.com/{i}">Snippet {i}</a>
                </div>
                """
            return f"<html><body><div class='results'>{items}</div></body></html>".encode()

        def __exit__(self, *args):
            pass

        def __enter__(self):
            return self

    class MockUrlOpen:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return MockResponse()

        def __exit__(self, *args):
            pass

        def read(self):
            return MockResponse().read()

    mock_urlopen.return_value = MockUrlOpen()

    result = search_web("test", count=3)
    assert len(result["results"]) == 3
    assert result["count"] == 3


def test_search_result_to_dict():
    """SearchResult.to_dict 回傳正確的 dict。"""
    from orchestrator.search import SearchResult

    r = SearchResult(title="T", url="https://u.com", snippet="Snippet text")
    d = r.to_dict()
    assert d == {"title": "T", "url": "https://u.com", "snippet": "Snippet text"}


def test_search_result_empty():
    """空的 SearchResult → to_dict 回傳空字串。"""
    from orchestrator.search import SearchResult

    r = SearchResult()
    assert r.to_dict() == {"title": "", "url": "", "snippet": ""}


# ── POST /search API ─────────────────────────────────────────────────────


@patch("orchestrator.executor_registry.run")
def test_search_api_success(mock_run):
    """POST /search → 回傳搜尋結果。"""
    mock_run.return_value = (
        '{"query":"python","results":[{"title":"Python","url":"https://python.org",'
        '"snippet":"A language."}],"count":1}'
    )
    r = client.post("/search", json={"query": "python", "count": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "python"
    assert len(body["results"]) == 1
    assert body["results"][0]["title"] == "Python"


@patch("orchestrator.executor_registry.run")
def test_search_api_error(mock_run):
    """executor 拋錯 → 回傳 error + 空結果。"""
    mock_run.side_effect = RuntimeError("Search failed")

    r = client.post("/search", json={"query": "python"})
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is not None
    assert body["results"] == []


@patch("orchestrator.executor_registry.run")
def test_search_api_respects_count(mock_run):
    """count 參數限制回傳結果。"""
    mock_run.return_value = (
        '{"query":"test","results":[{"title":"A","url":"","snippet":""},'
        '{"title":"B","url":"","snippet":""},{"title":"C","url":"","snippet":""}],'
        '"count":3}'
    )
    r = client.post("/search", json={"query": "test", "count": 2})
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 2
    assert body["count"] == 2


@patch("orchestrator.executor_registry.run")
def test_search_api_empty_query(mock_run):
    """空 query → executor 還是呼叫，但回傳空結果。"""
    mock_run.return_value = '{"query":"","results":[],"count":0}'
    r = client.post("/search", json={"query": ""})
    assert r.status_code == 200
    body = r.json()
    assert body["results"] == []


# ── GET /search API ──────────────────────────────────────────────────────


@patch("orchestrator.executor_registry.run")
def test_search_get_success(mock_run):
    """GET /search?q=python → 回傳搜尋結果。"""
    mock_run.return_value = (
        '{"query":"python","results":[{"title":"Python","url":"https://python.org",'
        '"snippet":"A language."}],"count":1}'
    )
    r = client.get("/search?q=python")
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "python"
    assert len(body["results"]) == 1


@patch("orchestrator.executor_registry.run")
def test_search_get_with_count(mock_run):
    """GET /search?q=test&count=2 → count 參數有效。"""
    mock_run.return_value = (
        '{"query":"test","results":[{"title":"A","url":"","snippet":""},'
        '{"title":"B","url":"","snippet":""}],"count":2}'
    )
    r = client.get("/search?q=test&count=2")
    assert r.status_code == 200
    assert len(r.json()["results"]) == 2


@patch("orchestrator.executor_registry.run")
def test_search_get_error(mock_run):
    """GET /search 拋錯 → error + 空結果。"""
    mock_run.side_effect = RuntimeError("fail")
    r = client.get("/search?q=test")
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is not None
    assert body["results"] == []


# ── /executors lists web-search ────────────────────────────────────────────


def test_executors_includes_web_search():
    """GET /executors → 包含 web-search。"""
    r = client.get("/executors")
    assert r.status_code == 200
    names = [e["name"] for e in r.json()["executors"]]
    assert "web-search" in names


# ── CLI wrapper ────────────────────────────────────────────────────────────


def test_cli_module_runs():
    """scripts/search-web.py 可以作為 module 執行。"""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/search-web.py", "hello"],
        capture_output=True, text=True, timeout=10,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0
    import json
    data = json.loads(result.stdout)
    assert "query" in data
    assert "results" in data