"""
Per-loop state file — the agent forgets, the file remembers.

Usage:
    from orchestrator.state import load_state, save_state, update_from_beat

    state = load_state()           # start of cycle
    # ... do work ...
    save_state(state)              # end of cycle

The file lives at data/state.json, human-readable JSON.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "state.json"

DEFAULT_STATE: dict[str, Any] = {
    "loop_id": "agentos-heartbeat",
    "last_beat_n": 0,
    "last_run": None,
    "queue_depth": 0,
    "budget_spent_today": 0.0,
    "budget_remaining": 5.0,
    "last_beat_status": "idle",
    "in_progress_tasks": [],
    "escalated_today": 0,
    "passed_today": 0,
    "eval_last_score": None,
}


def _defaults() -> dict[str, Any]:
    """Return a fresh copy of DEFAULT_STATE."""
    return dict(DEFAULT_STATE)


def load_state() -> dict[str, Any]:
    """Read state.json or return defaults on first run / corruption."""
    try:
        raw = STATE_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        merged = _defaults()
        merged.update(data)
        return merged
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return _defaults()


def save_state(state: dict[str, Any]) -> None:
    """Write state dict to state.json."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def update_from_beat(beat_result: dict[str, Any]) -> dict[str, Any]:
    """Merge one heartbeat beat result into state and persist.

    Call this at the end of run_once().
    """
    state = load_state()
    state["last_beat_n"] = beat_result.get("beat_n", state["last_beat_n"])
    state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    # Budget
    spent = beat_result.get("spent_before", 0.0)
    state["budget_spent_today"] = spent

    # Queue
    state["queue_depth"] = beat_result.get("queue_depth", 0)

    # Status
    exhausted_pre = beat_result.get("budget_exhausted_pre", False)
    exhausted_post = beat_result.get("budget_exhausted_post", False)
    if exhausted_pre or exhausted_post:
        state["last_beat_status"] = "budget_exhausted"
    else:
        loop = beat_result.get("loop") or {}
        if loop.get("escalated", 0) > 0:
            state["last_beat_status"] = "escalated"
        elif loop.get("passed", 0) > 0:
            state["last_beat_status"] = "passed"
        else:
            state["last_beat_status"] = "idle"

        state["escalated_today"] += loop.get("escalated", 0)
        state["passed_today"] += loop.get("passed", 0)

    save_state(state)
    return state
