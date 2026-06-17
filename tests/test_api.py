"""API route tests using FastAPI TestClient."""
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from api.main import app, sessions

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ── /task/submit ──────────────────────────────────────────────────────────

def test_submit_returns_session_and_questions():
    r = client.post("/task/submit", json={"task": "build cashflow calculator"})
    assert r.status_code == 200
    body = r.json()
    assert "session_id" in body
    assert len(body["session_id"]) == 8
    assert len(body["questions"]) == 6
    assert body["questions"][0]["key"] == "why"


def test_submit_empty_task_rejected():
    r = client.post("/task/submit", json={"task": ""})
    assert r.status_code == 422


def test_submit_missing_task_rejected():
    r = client.post("/task/submit", json={})
    assert r.status_code == 422


# ── /task/approve ─────────────────────────────────────────────────────────

def test_approve_unknown_session_returns_404():
    r = client.post("/task/approve", json={"session_id": "notexist", "spec": {}})
    assert r.status_code == 404


def test_approve_valid_session_starts_loop():
    # First create a session
    sub = client.post("/task/submit", json={"task": "test task"})
    session_id = sub.json()["session_id"]

    spec = {
        "why": "test task",
        "io": "input x → output y",
        "taste": "should work",
        "boundary": "no side effects",
        "stop_metric": "output contains y",
        "max_rounds": "2",
    }

    # Mock the loop so we don't actually call LLMs
    with patch("api.main._run_and_push", new=AsyncMock()):
        r = client.post("/task/approve", json={"session_id": session_id, "spec": spec})

    assert r.status_code == 200
    assert r.json()["ok"] is True


# ── /task/deliver ─────────────────────────────────────────────────────────

def test_deliver_unknown_session_returns_404():
    r = client.post("/task/deliver", json={"session_id": "notexist", "accepted": True})
    assert r.status_code == 404


def test_deliver_accepted():
    sub = client.post("/task/submit", json={"task": "deliver test"})
    session_id = sub.json()["session_id"]
    r = client.post("/task/deliver", json={"session_id": session_id, "accepted": True, "feedback": ""})
    assert r.status_code == 200
    assert r.json()["accepted"] is True


def test_deliver_rejected_with_feedback():
    sub = client.post("/task/submit", json={"task": "deliver test 2"})
    session_id = sub.json()["session_id"]
    r = client.post("/task/deliver", json={"session_id": session_id, "accepted": False, "feedback": "wrong output"})
    assert r.status_code == 200
    assert r.json()["accepted"] is False


def test_deliver_missing_accepted_rejected():
    r = client.post("/task/deliver", json={"session_id": "x"})
    assert r.status_code == 422


# ── /cost ─────────────────────────────────────────────────────────────────

def test_cost_returns_valid_shape():
    r = client.get("/cost")
    assert r.status_code == 200
    body = r.json()
    assert "total_usd" in body
    assert "calls" in body
    assert body["total_usd"] >= 0
    assert body["calls"] >= 0


# ── align.core ────────────────────────────────────────────────────────────

def test_parse_answers_arrow_syntax():
    from align.core import parse_answers_to_spec
    spec = parse_answers_to_spec({
        "why": "build cashflow",
        "io": "rent=30000 → cashflow=9000",
        "taste": "show breakdown, handle negatives",
        "boundary": "no tax",
        "stop_metric": "contains cashflow",
        "max_rounds": "3",
    })
    assert spec.io_example["input"] == "rent=30000"
    assert spec.io_example["expected_output"] == "cashflow=9000"
    assert len(spec.taste) == 2
    assert spec.max_rounds == 3


def test_parse_answers_no_arrow_fallback():
    from align.core import parse_answers_to_spec
    spec = parse_answers_to_spec({
        "why": "do something",
        "io": "just some text",
        "taste": "",
        "boundary": "",
        "stop_metric": "done",
        "max_rounds": "5",
    })
    assert spec.io_example["input"] == "just some text"
