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
    from orchestrator.maker import MakeResult
    with patch("api.main.run_maker") as mock_maker:
        mock_maker.return_value = MakeResult.from_subprocess("def hello(): pass")
        r = client.post("/task/make", json={"why": "write hello function"})
    assert r.status_code == 200
    body = r.json()
    assert body["output"] == "def hello(): pass"
    assert body["error"] == ""


def test_make_with_executor():
    """executor=web-llm-genspark passes executor to spec."""
    from orchestrator.maker import MakeResult
    with patch("api.main.run_maker") as mock_maker:
        mock_maker.return_value = MakeResult.from_subprocess("some output")
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


# ── /brain/consolidate (記憶固化) ────────────────────────────────────────────


def test_consolidate_single_experience():
    """單條經驗 → 回傳 ok + 1 條 gene。"""
    r = client.post("/brain/consolidate", json={
        "experiences": [
            {"domain": "coding", "type": "bug-fix", "what": "settings.json executor 區塊不可刪除"}
        ]
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["genes"]) == 1
    assert body["genes"][0]["entry_id"] != ""


def test_consolidate_multiple_experiences():
    """多條經驗 → 全部寫入，回傳對應數量。"""
    r = client.post("/brain/consolidate", json={
        "experiences": [
            {"domain": "architecture", "type": "decision", "what": "config-driven 比硬編碼好擴充"},
            {"domain": "workflow", "type": "pattern", "what": "commit 前先問用戶確認"},
        ]
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["genes"]) == 2


def test_consolidate_with_fix():
    """含 fix 的 bug-fix 經驗 → key 前綴正確。"""
    r = client.post("/brain/consolidate", json={
        "experiences": [
            {
                "domain": "debugging",
                "type": "bug-fix",
                "what": "settings.json 刪了 executors 導致 4 個 executor 消失",
                "fix": "restore with git checkout origin/main",
            }
        ]
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["genes"]) == 1
    assert body["genes"][0]["key"].startswith("gene/debugging/")


def test_consolidate_empty_experiences_rejected():
    """空 experiences 陣列 → 422。"""
    r = client.post("/brain/consolidate", json={"experiences": []})
    assert r.status_code == 422


def test_consolidate_missing_fields_rejected():
    """缺少 domain 或 what → 422。"""
    r = client.post("/brain/consolidate", json={
        "experiences": [{"type": "insight"}]
    })
    assert r.status_code == 422