"""Tests for orchestrator/triage.py — auto-suggest logic (no API)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from orchestrator import triage


def _make_escalated_task(
    task_id: str = "t-123",
    fingerprint: str = "tests/test_foo.py::test_bar",
    why: str = "修復失敗測試：tests/test_foo.py::test_bar",
    feedback: str = "max_rounds exhausted",
) -> dict:
    """Helper to create a realistic escalated task dict."""
    return {
        "task_id": task_id,
        "status": "escalated",
        "spec_json": json.dumps({
            "why": why,
            "io_example": {"input": fingerprint, "expected_output": "pass"},
            "taste": [],
            "boundaries": [],
            "stop_on_metric": "quality",
            "max_rounds": 3,
        }),
        "last_feedback": feedback,
        "notes": {"source": "A", "fingerprint": fingerprint},
        "attempt_count": 2,
        "last_score": 2.0,
    }


class TestExtractKeywords:
    def test_extracts_from_fingerprint(self):
        task = _make_escalated_task(fingerprint="tests/test_auth.py::test_timeout")
        kw = triage._extract_keywords(task)
        assert "auth" in kw and "timeout" in kw

    def test_extracts_from_why(self):
        task = _make_escalated_task(fingerprint="", why="修復登入逾時問題")
        kw = triage._extract_keywords(task)
        assert "修復登入逾時問題" in kw

    def test_falls_back_to_task_id(self):
        task = _make_escalated_task(fingerprint="", why="", feedback="")
        kw = triage._extract_keywords(task)
        assert kw == task["task_id"]

    def test_strips_test_prefix(self):
        task = _make_escalated_task(
            fingerprint="tests/test_login.py::test_login_timeout"
        )
        kw = triage._extract_keywords(task)
        assert "login" in kw
        assert "test_login" not in kw  # prefix stripped

    def test_handles_spec_json_already_dict(self):
        """spec_json could already be a dict when constructed programmatically."""
        task = _make_escalated_task(fingerprint="")
        task["spec_json"] = {"why": "修復登入問題", "max_rounds": 3}
        kw = triage._extract_keywords(task)
        assert "修復登入問題" in kw


class TestSuggestFix:
    def test_suggest_finds_match(self, monkeypatch):
        task = _make_escalated_task(fingerprint="tests/test_auth.py::test_timeout")

        fake_brain = [
            {
                "key": "gene/workflow/login-timeout",
                "content": "修好登入逾時",
                "created_at": "2026-06-24T...",
            },
        ]

        def fake_search(query, limit=10):
            return fake_brain

        monkeypatch.setattr("orchestrator.knowledge.search_knowledge", fake_search)

        result = triage.suggest_fix(task)
        assert result is not None
        assert result["task_id"] == "t-123"
        assert len(result["suggestions"]) == 1
        assert "登入" in result["suggestions"][0]["content"]

    def test_suggest_empty_brain(self, monkeypatch):
        task = _make_escalated_task(fingerprint="tests/test_new.py::test_unknown")

        def fake_search(query, limit=10):
            return []

        monkeypatch.setattr("orchestrator.knowledge.search_knowledge", fake_search)

        result = triage.suggest_fix(task)
        assert result is None

    def test_suggest_sorts_by_similarity(self, monkeypatch):
        task = _make_escalated_task(fingerprint="tests/test_auth.py::test_login")

        fake_brain = [
            {
                "key": "gene/workflow/unrelated",
                "content": "完全不相關的內容 abc xyz",
                "created_at": "t1",
            },
            {
                "key": "gene/workflow/login-help",
                "content": "login auth timeout 登入逾時修復",
                "created_at": "t2",
            },
        ]

        def fake_search(query, limit=10):
            return fake_brain

        monkeypatch.setattr("orchestrator.knowledge.search_knowledge", fake_search)

        result = triage.suggest_fix(task)
        assert result is not None
        # login-help should rank higher due to keyword overlap
        assert result["suggestions"][0]["similarity"] >= result["suggestions"][-1][
            "similarity"
        ]

    def test_suggest_handles_knowledge_error(self, monkeypatch):
        """When knowledge.search_knowledge raises, suggest_fix returns None gracefully."""
        task = _make_escalated_task(fingerprint="tests/test_auth.py::test_timeout")

        def fake_search(query, limit=10):
            raise RuntimeError("db connection lost")

        monkeypatch.setattr("orchestrator.knowledge.search_knowledge", fake_search)

        result = triage.suggest_fix(task)
        assert result is None
