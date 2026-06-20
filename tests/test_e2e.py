"""End-to-end integration tests for /task/make and /task/verify endpoints."""
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


# ── /task/make ─────────────────────────────────────────────────────────────


def test_make_success():
    """POST /task/make → mock run_maker → output returned."""
    with patch("api.main.run_maker") as mock_maker:
        mock_maker.return_value = "def hello(): pass"
        r = client.post("/task/make", json={"why": "write hello function"})
    assert r.status_code == 200
    body = r.json()
    assert body["output"] == "def hello(): pass"
    assert body["error"] == ""


def test_make_with_executor():
    """executor=web-llm-genspark passes executor to spec."""
    with patch("api.main.run_maker") as mock_maker:
        mock_maker.return_value = "some output"
        r = client.post("/task/make", json={
            "why": "explain recursion",
            "executor": "web-llm-genspark",
        })
    assert r.status_code == 200
    # Verify the spec was created with the custom executor
    called_spec = mock_maker.call_args[0][0]
    assert called_spec.executor == "web-llm-genspark"


def test_make_dangerous_blocked():
    """危險任務應被 safety gate 擋住，不呼叫 run_maker。"""
    with patch("api.main.run_maker") as mock_maker:
        r = client.post("/task/make", json={"why": "rm -rf /production"})
    assert r.status_code == 200
    body = r.json()
    assert body["error"] != ""
    assert "blocked" in body["error"].lower()
    mock_maker.assert_not_called()


def test_make_error_handling():
    """run_maker 拋出例外時應回傳 error。"""
    with patch("api.main.run_maker") as mock_maker:
        mock_maker.side_effect = RuntimeError("LLM call failed")
        r = client.post("/task/make", json={"why": "write code"})
    assert r.status_code == 200
    body = r.json()
    assert body["output"] == ""
    assert "LLM call failed" in body["error"]


# ── /task/verify ───────────────────────────────────────────────────────────


def test_verify_pytest_pass():
    """POST /task/verify → mock run_verification → pass result."""
    with patch("api.main.run_verification") as mock_verify:
        mock_verify.return_value = {
            "status": "pass",
            "score": 10.0,
            "feedback": "All tests passed",
            "passed": True,
            "source": "pytest",
        }
        r = client.post("/task/verify", json={
            "why": "build calculator",
            "output": "def add(a,b): return a+b",
        })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pass"
    assert body["score"] == 10.0
    assert body["passed"] is True
    assert body["source"] == "pytest"


def test_verify_pytest_fail():
    """POST /task/verify → mock run_verification → retry result."""
    with patch("api.main.run_verification") as mock_verify:
        mock_verify.return_value = {
            "status": "retry",
            "score": 2.0,
            "feedback": "AssertionError: expected 5, got 3",
            "passed": False,
            "source": "pytest",
        }
        r = client.post("/task/verify", json={
            "why": "build calculator",
            "output": "def add(a,b): return a-b",
        })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "retry"
    assert body["score"] == 2.0
    assert body["passed"] is False
    assert "AssertionError" in body["feedback"]


def test_verify_no_test():
    """無測試的純文字任務 → source=claude-cli。"""
    with patch("api.main.run_verification") as mock_verify:
        mock_verify.return_value = {
            "status": "pass",
            "score": 7.5,
            "feedback": "Looks good",
            "passed": True,
            "source": "claude-cli",
        }
        r = client.post("/task/verify", json={
            "why": "explain TCP handshake",
            "output": "TCP uses SYN, SYN-ACK, ACK",
        })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pass"
    assert body["source"] == "claude-cli"


def test_verify_error_handling():
    """run_verification 拋出例外時應回傳 escalate。"""
    with patch("api.main.run_verification") as mock_verify:
        mock_verify.side_effect = RuntimeError("Checker crashed")
        r = client.post("/task/verify", json={
            "why": "test",
            "output": "output",
        })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "escalate"
    assert body["score"] == 0.0


def test_verify_dangerous_input_escalates():
    """危險內容 — verify 無 safety gate，run_verification 拋錯則 escalate。"""
    with patch("api.main.run_verification") as mock_verify:
        mock_verify.side_effect = RuntimeError("dangerous content rejected")
        r = client.post("/task/verify", json={
            "why": "DROP TABLE users; --",
            "output": "malicious",
        })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "escalate"
    assert body["score"] == 0.0