"""SQLite-backed audit trail for request routing decisions.

All audit writes are centralized here. Audit failures must never block the
main flow, so public write functions catch exceptions, emit stderr warnings,
and increment an in-process failure counter.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from pathlib import Path
from typing import Any

_DB_LOCK = threading.Lock()
_SCHEMA_ENSURED_FOR_PATH: str = ""
_AUDIT_FAILURE_COUNT = 0

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "decisions.db"

REQUEST_TRACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS request_trace (
  request_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  entrypoint TEXT NOT NULL,
  raw_task TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  latest_status TEXT,
  notes_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_request_trace_session_id ON request_trace(session_id);
CREATE INDEX IF NOT EXISTS idx_request_trace_created_at ON request_trace(created_at);
"""

ROUTING_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS routing_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  stage TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  round_n INTEGER,
  decision TEXT NOT NULL,
  decision_source TEXT NOT NULL,
  matched_keyword TEXT,
  confidence REAL,
  classifier_model TEXT,
  fallback_reason TEXT,
  pre_policy_model TEXT,
  pre_policy_skills_json TEXT NOT NULL DEFAULT '[]',
  pre_policy_tools_json TEXT NOT NULL DEFAULT '[]',
  final_model TEXT,
  final_skills_json TEXT NOT NULL DEFAULT '[]',
  final_tools_json TEXT NOT NULL DEFAULT '[]',
  policy_applied INTEGER NOT NULL DEFAULT 0,
  policy_changed INTEGER NOT NULL DEFAULT 0,
  requires_human_confirm INTEGER NOT NULL DEFAULT 0,
  violations_json TEXT NOT NULL DEFAULT '[]',
  details_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (request_id) REFERENCES request_trace(request_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_routing_events_request_id ON routing_events(request_id, event_id);
CREATE INDEX IF NOT EXISTS idx_routing_events_type ON routing_events(event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_routing_events_stage ON routing_events(stage, created_at);
"""


def _db_path() -> Path:
    override = os.environ.get("AGENTOS_DECISIONS_DB_PATH", "").strip()
    return Path(override) if override else DEFAULT_DB_PATH


def get_db_path() -> Path:
    return _db_path()


def _json(data: Any, *, default: Any) -> str:
    if data is None:
        data = default
    return json.dumps(data, ensure_ascii=False)


def _warn(msg: str) -> None:
    global _AUDIT_FAILURE_COUNT
    _AUDIT_FAILURE_COUNT += 1
    print(f"[decision_log] WARNING: {msg}", file=sys.stderr)


def get_audit_failure_count() -> int:
    return _AUDIT_FAILURE_COUNT


def reset_audit_failure_count() -> None:
    global _AUDIT_FAILURE_COUNT
    _AUDIT_FAILURE_COUNT = 0


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema() -> None:
    """Ensure schema exists. Path-aware cache skips redundant ops after first call."""
    global _SCHEMA_ENSURED_FOR_PATH
    current_path = str(_db_path())
    if _SCHEMA_ENSURED_FOR_PATH == current_path:
        return
    with _DB_LOCK:
        with _connect() as conn:
            conn.executescript(REQUEST_TRACE_SCHEMA)
            conn.executescript(ROUTING_EVENTS_SCHEMA)
    _SCHEMA_ENSURED_FOR_PATH = current_path


def record_request_trace(
    *,
    request_id: str,
    session_id: str,
    entrypoint: str,
    raw_task: str,
    latest_status: str | None = None,
    notes: dict[str, Any] | None = None,
) -> bool:
    ensure_schema()
    try:
        with _DB_LOCK:
            with _connect() as conn:
                conn.execute(
                    """
                    INSERT INTO request_trace (
                      request_id, session_id, entrypoint, raw_task, latest_status, notes_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(request_id) DO UPDATE SET
                      session_id=excluded.session_id,
                      entrypoint=excluded.entrypoint,
                      raw_task=excluded.raw_task,
                      latest_status=excluded.latest_status,
                      notes_json=excluded.notes_json
                    """,
                    (
                        request_id,
                        session_id,
                        entrypoint,
                        raw_task,
                        latest_status,
                        _json(notes, default={}),
                    ),
                )
        return True
    except Exception as exc:
        _warn(f"record_request_trace failed for request_id={request_id}: {exc}")
        return False


def update_request_status(request_id: str, latest_status: str) -> bool:
    ensure_schema()
    try:
        with _DB_LOCK:
            with _connect() as conn:
                conn.execute(
                    "UPDATE request_trace SET latest_status = ? WHERE request_id = ?",
                    (latest_status, request_id),
                )
        return True
    except Exception as exc:
        _warn(f"update_request_status failed for request_id={request_id}: {exc}")
        return False


def record_intent_gate(
    *,
    request_id: str,
    session_id: str,
    decision: str,
    decision_source: str,
    matched_keyword: str | None = None,
    confidence: float | None = None,
    classifier_model: str | None = None,
    fallback_reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> bool:
    return _record_routing_event(
        request_id=request_id,
        session_id=session_id,
        event_type="intent_gate",
        stage="api",
        round_n=None,
        decision=decision,
        decision_source=decision_source,
        matched_keyword=matched_keyword,
        confidence=confidence,
        classifier_model=classifier_model,
        fallback_reason=fallback_reason,
        pre_policy_model=None,
        pre_policy_skills=None,
        pre_policy_tools=None,
        final_model=None,
        final_skills=None,
        final_tools=None,
        policy_applied=0,
        policy_changed=0,
        requires_human_confirm=0,
        violations=None,
        details=details,
    )


def record_execution_route(
    *,
    request_id: str,
    session_id: str,
    round_n: int | None,
    decision: str,
    decision_source: str,
    matched_keyword: str | None = None,
    confidence: float | None = None,
    classifier_model: str | None = None,
    fallback_reason: str | None = None,
    pre_policy_model: str | None,
    pre_policy_skills: list[str] | None,
    pre_policy_tools: list[str] | None,
    final_model: str | None,
    final_skills: list[str] | None,
    final_tools: list[str] | None,
    policy_applied: bool,
    policy_changed: bool,
    requires_human_confirm: bool,
    violations: list[str] | None,
    details: dict[str, Any] | None = None,
) -> bool:
    return _record_routing_event(
        request_id=request_id,
        session_id=session_id,
        event_type="execution_route",
        stage="router",
        round_n=round_n,
        decision=decision,
        decision_source=decision_source,
        matched_keyword=matched_keyword,
        confidence=confidence,
        classifier_model=classifier_model,
        fallback_reason=fallback_reason,
        pre_policy_model=pre_policy_model,
        pre_policy_skills=pre_policy_skills,
        pre_policy_tools=pre_policy_tools,
        final_model=final_model,
        final_skills=final_skills,
        final_tools=final_tools,
        policy_applied=1 if policy_applied else 0,
        policy_changed=1 if policy_changed else 0,
        requires_human_confirm=1 if requires_human_confirm else 0,
        violations=violations,
        details=details,
    )


def _record_routing_event(
    *,
    request_id: str,
    session_id: str,
    event_type: str,
    stage: str,
    round_n: int | None,
    decision: str,
    decision_source: str,
    matched_keyword: str | None,
    confidence: float | None,
    classifier_model: str | None,
    fallback_reason: str | None,
    pre_policy_model: str | None,
    pre_policy_skills: list[str] | None,
    pre_policy_tools: list[str] | None,
    final_model: str | None,
    final_skills: list[str] | None,
    final_tools: list[str] | None,
    policy_applied: int,
    policy_changed: int,
    requires_human_confirm: int,
    violations: list[str] | None,
    details: dict[str, Any] | None,
) -> bool:
    ensure_schema()
    try:
        with _DB_LOCK:
            with _connect() as conn:
                conn.execute(
                    """
                    INSERT INTO routing_events (
                      request_id, session_id, event_type, stage, round_n,
                      decision, decision_source, matched_keyword, confidence,
                      classifier_model, fallback_reason,
                      pre_policy_model, pre_policy_skills_json, pre_policy_tools_json,
                      final_model, final_skills_json, final_tools_json,
                      policy_applied, policy_changed, requires_human_confirm,
                      violations_json, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request_id,
                        session_id,
                        event_type,
                        stage,
                        round_n,
                        decision,
                        decision_source,
                        matched_keyword,
                        confidence,
                        classifier_model,
                        fallback_reason,
                        pre_policy_model,
                        _json(pre_policy_skills, default=[]),
                        _json(pre_policy_tools, default=[]),
                        final_model,
                        _json(final_skills, default=[]),
                        _json(final_tools, default=[]),
                        policy_applied,
                        policy_changed,
                        requires_human_confirm,
                        _json(violations, default=[]),
                        _json(details, default={}),
                    ),
                )
        return True
    except Exception as exc:
        _warn(
            f"record_routing_event failed for request_id={request_id} event_type={event_type}: {exc}"
        )
        return False
