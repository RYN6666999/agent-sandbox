"""Metrics collection for the optimization loop.

Stores evaluation results in data/metrics.db for reliability/validity tracking.
Part of the OPTIMIZATION.md closed loop: run → trace → evaluate → reflect → propose.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DB_LOCK = threading.Lock()
_DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "metrics.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scenario_id TEXT NOT NULL,
  routing TEXT NOT NULL,
  score REAL NOT NULL,
  passed INTEGER NOT NULL,
  timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_scenario ON eval_results(scenario_id);
CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON eval_results(timestamp);
"""


def _db_path() -> Path:
    override = os.environ.get("AGENTOS_METRICS_DB_PATH", "").strip()
    return Path(override) if override else _DEFAULT_DB_PATH


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema() -> bool:
    try:
        with _DB_LOCK:
            with _connect() as conn:
                conn.executescript(_SCHEMA)
        return True
    except Exception:
        return False


def record_eval(scenario_id: str, routing: str, score: float, passed: bool) -> None:
    """Record one evaluation result."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    try:
        with _DB_LOCK:
            with _connect() as conn:
                conn.execute(
                    "INSERT INTO eval_results(scenario_id, routing, score, passed, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (scenario_id, routing, score, 1 if passed else 0, ts),
                )
    except Exception:
        pass  # best-effort


def get_metrics(since_hours: int = 24) -> dict[str, Any]:
    """Aggregate metrics since a given time window."""
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM eval_results WHERE timestamp >= datetime('now', ? || ' hours')",
                (f"-{since_hours}",),
            ).fetchone()[0]
            passed = conn.execute(
                "SELECT COUNT(*) FROM eval_results WHERE passed=1 AND timestamp >= datetime('now', ? || ' hours')",
                (f"-{since_hours}",),
            ).fetchone()[0]
            avg_score = conn.execute(
                "SELECT COALESCE(AVG(score), 0.0) FROM eval_results WHERE timestamp >= datetime('now', ? || ' hours')",
                (f"-{since_hours}",),
            ).fetchone()[0]
            by_category = conn.execute(
                """
                SELECT e.scenario_id, AVG(e.score) as avg_score, COUNT(*) as runs
                FROM eval_results e
                WHERE e.timestamp >= datetime('now', ? || ' hours')
                GROUP BY e.scenario_id
                """,
                (f"-{since_hours}",),
            ).fetchall()
    categories = {}
    for row in by_category:
        categories[row["scenario_id"]] = {
            "avg_score": round(row["avg_score"], 2),
            "runs": row["runs"],
        }
    return {
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "avg_score": round(avg_score, 2),
        "by_scenario": categories,
        "since_hours": since_hours,
    }


def reliability_score(scenario_id: str, n_runs: int = 3) -> float:
    """Run a scenario N times and return the score stability (1.0 - std/10)."""
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT score FROM eval_results WHERE scenario_id=? ORDER BY timestamp DESC LIMIT ?",
                (scenario_id, n_runs),
            ).fetchall()
    if len(rows) < 2:
        return 1.0
    scores = [r["score"] for r in rows]
    mean = sum(scores) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)
    std = variance ** 0.5
    return round(max(0.0, 1.0 - std / 10.0), 3)


def validity_score(category: str | None = None) -> float:
    """Overall pass rate across all recorded evals."""
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            if category:
                total = conn.execute(
                    "SELECT COUNT(*) FROM eval_results e WHERE e.scenario_id LIKE ?",
                    (f"{category}%",),
                ).fetchone()[0]
                passed = conn.execute(
                    "SELECT COUNT(*) FROM eval_results e WHERE e.passed=1 AND e.scenario_id LIKE ?",
                    (f"{category}%",),
                ).fetchone()[0]
            else:
                total = conn.execute(
                    "SELECT COUNT(*) FROM eval_results"
                ).fetchone()[0]
                passed = conn.execute(
                    "SELECT COUNT(*) FROM eval_results WHERE passed=1"
                ).fetchone()[0]
    return round(passed / total, 3) if total else 0.0
