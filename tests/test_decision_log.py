"""Decision log tests for SQLite audit trail."""
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.main import app, sessions
from contracts.routing_triple import RoutingTriple
from orchestrator import decision_log
from router import route
from router.classifier import ClassifyResult
from router.rules import TaskType

client = TestClient(app)


@pytest.fixture()
def temp_decision_db(tmp_path, monkeypatch):
    db_path = tmp_path / "decisions.db"
    monkeypatch.setenv("AGENTOS_DECISIONS_DB_PATH", str(db_path))
    sessions.clear()
    decision_log.reset_audit_failure_count()
    decision_log._SCHEMA_ENSURED = False  # 清除 cache，讓 ensure_schema 對新的 temp 路徑生效
    decision_log.ensure_schema()
    yield db_path
    sessions.clear()


def _rows(db_path: Path, sql: str, params: tuple = ()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _one(db_path: Path, sql: str, params: tuple = ()):
    rows = _rows(db_path, sql, params)
    assert rows, f"no rows for query: {sql}"
    return rows[0]


# ── Layer 1: Schema / Writer ─────────────────────────────────────────────

def test_decision_log_schema_and_writer_roundtrip(temp_decision_db):
    assert decision_log.record_request_trace(
        request_id="req-1",
        session_id="req-1",
        entrypoint="chat",
        raw_task="what is cashflow?",
        latest_status="running",
        notes={"request_id_equals_session_id": True},
    ) is True
    assert decision_log.record_intent_gate(
        request_id="req-1",
        session_id="req-1",
        decision="direct",
        decision_source="heuristic",
        matched_keyword="what",
        confidence=0.95,
        details={"looks_like_question": True},
    ) is True
    assert decision_log.record_execution_route(
        request_id="req-1",
        session_id="req-1",
        round_n=1,
        decision="summary",
        decision_source="rule",
        matched_keyword="summarize",
        confidence=0.85,
        classifier_model=None,
        fallback_reason=None,
        pre_policy_model="gemini-flash",
        pre_policy_skills=[],
        pre_policy_tools=["file"],
        final_model="gemini-flash",
        final_skills=[],
        final_tools=["file"],
        policy_applied=True,
        policy_changed=False,
        requires_human_confirm=False,
        violations=[],
        details={"retry_count": 0},
    ) is True
    assert decision_log.record_execution_route(
        request_id="req-1",
        session_id="req-1",
        round_n=2,
        decision="summary",
        decision_source="rule",
        matched_keyword="summarize",
        confidence=0.85,
        classifier_model=None,
        fallback_reason=None,
        pre_policy_model="gemini-flash",
        pre_policy_skills=[],
        pre_policy_tools=["file"],
        final_model="gemini-flash",
        final_skills=[],
        final_tools=["file"],
        policy_applied=True,
        policy_changed=False,
        requires_human_confirm=False,
        violations=[],
        details={"retry_count": 0},
    ) is True

    req = _one(temp_decision_db, "SELECT * FROM request_trace WHERE request_id=?", ("req-1",))
    assert req["entrypoint"] == "chat"
    assert json.loads(req["notes_json"])["request_id_equals_session_id"] is True

    events = _rows(temp_decision_db, "SELECT * FROM routing_events WHERE request_id=? ORDER BY event_id", ("req-1",))
    assert [row["event_id"] for row in events] == [1, 2, 3]
    assert json.loads(events[0]["details_json"])["looks_like_question"] is True
    assert json.loads(events[1]["pre_policy_tools_json"]) == ["file"]
    assert json.loads(events[2]["details_json"])["retry_count"] == 0


def test_decision_log_fk_integrity(temp_decision_db):
    conn = sqlite3.connect(temp_decision_db)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO routing_events (
                  request_id, session_id, event_type, stage, decision, decision_source
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("missing", "missing", "execution_route", "router", "feature", "rule"),
            )
    finally:
        conn.close()


# ── Layer 2: Behavior ────────────────────────────────────────────────────

def test_execution_route_rule_hit_logged(temp_decision_db):
    decision_log.record_request_trace(
        request_id="rule-1",
        session_id="rule-1",
        entrypoint="chat",
        raw_task="summarize this document into 3 bullet points",
    )

    route(
        "summarize this document into 3 bullet points",
        request_id="rule-1",
        session_id="rule-1",
        round_n=1,
    )

    row = _one(
        temp_decision_db,
        "SELECT * FROM routing_events WHERE request_id=? AND event_type='execution_route'",
        ("rule-1",),
    )
    assert row["decision_source"] == "rule"
    assert row["matched_keyword"]
    assert row["confidence"] is not None
    assert row["policy_applied"] == 1
    assert row["policy_changed"] == 0
    assert json.loads(row["violations_json"]) == []


def test_execution_route_llm_fallback_logged(temp_decision_db):
    decision_log.record_request_trace(
        request_id="fallback-1",
        session_id="fallback-1",
        entrypoint="chat",
        raw_task="xyzzyx zork blorp",
    )

    with patch(
        "router.llm_classify_detailed",
        return_value=ClassifyResult(
            task_type=TaskType.FEATURE,
            confidence=0.3,
            source="fallback",
            classifier_model="agnes",
            fallback_reason="provider timeout",
            retry_count=0,
        ),
    ):
        route("xyzzyx zork blorp", request_id="fallback-1", session_id="fallback-1", round_n=1)

    row = _one(
        temp_decision_db,
        "SELECT * FROM routing_events WHERE request_id=? AND event_type='execution_route'",
        ("fallback-1",),
    )
    assert row["decision_source"] == "fallback"
    assert row["fallback_reason"] == "provider timeout"
    assert row["classifier_model"] == "agnes"


def test_execution_route_policy_override_logged(temp_decision_db):
    decision_log.record_request_trace(
        request_id="danger-1",
        session_id="danger-1",
        entrypoint="chat",
        raw_task="delete all records from the database",
    )

    with patch(
        "router.get_triple",
        return_value=RoutingTriple(
            model="agnes",
            skills=["caveman"],
            mcp_tools=["file"],
            confidence=0.8,
        ),
    ):
        route(
            "delete all records from the database",
            request_id="danger-1",
            session_id="danger-1",
            round_n=1,
        )

    row = _one(
        temp_decision_db,
        "SELECT * FROM routing_events WHERE request_id=? AND event_type='execution_route'",
        ("danger-1",),
    )
    assert row["policy_applied"] == 1
    assert row["policy_changed"] == 1
    assert row["requires_human_confirm"] == 1
    violations = json.loads(row["violations_json"])
    assert violations
    assert any("human confirmation required" in item for item in violations)


# ── Layer 3: Timeline completeness ───────────────────────────────────────

def test_legacy_submit_writes_align_intent_gate(temp_decision_db):
    response = client.post("/task/submit", json={"task": "build cashflow calculator"})
    assert response.status_code == 200
    session_id = response.json()["session_id"]

    event = _one(
        temp_decision_db,
        "SELECT * FROM routing_events WHERE request_id=? ORDER BY event_id",
        (session_id,),
    )
    assert event["event_type"] == "intent_gate"
    assert event["decision"] == "align"
    assert event["decision_source"] == "legacy_submit"


def test_request_timeline_links_intent_gate_and_execution_route(temp_decision_db):
    def _drop_task(coro):
        coro.close()
        return None

    with patch("api.main.asyncio.create_task", side_effect=_drop_task):
        response = client.post("/chat", json={"task": "what is cashflow?"})
    assert response.status_code == 200
    session_id = response.json()["session_id"]
    request_id = sessions[session_id]["request_id"]

    route(
        "summarize this document into 3 bullet points",
        request_id=request_id,
        session_id=session_id,
        round_n=1,
    )

    events = _rows(
        temp_decision_db,
        "SELECT * FROM routing_events WHERE request_id=? ORDER BY event_id",
        (request_id,),
    )
    assert [row["event_type"] for row in events] == ["intent_gate", "execution_route"]
    assert [row["stage"] for row in events] == ["api", "router"]
    assert events[0]["decision"] == "direct"
    assert events[1]["decision_source"] == "rule"
