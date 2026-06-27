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


# ── /goal 機制 ─────────────────────────────────────────────────────────────

GOAL_PATH = Path(__file__).resolve().parent.parent / "data" / "goal.json"


def goal_load() -> dict[str, Any]:
    """Load the current /goal condition. Returns default (no goal) on missing file."""
    try:
        return json.loads(GOAL_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"active": False, "condition": "", "reason": ""}


def goal_save(condition: str, reason: str = "") -> None:
    """Set a new /goal condition."""
    data = {
        "active": bool(condition),
        "condition": condition,
        "reason": reason,
        "set_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    GOAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOAL_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def goal_clear() -> None:
    """Deactivate the current goal."""
    if GOAL_PATH.exists():
        data = json.loads(GOAL_PATH.read_text(encoding="utf-8"))
        data["active"] = False
        GOAL_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def goal_reached(loop_report: dict[str, Any]) -> bool:
    """Check whether the /goal condition has been met.

    Currently rule-based: goal is 'reached' when the run_loop report shows
    at least 1 passed task with 0 escalated.
    Future: pluggable checker (small model) subagent for arbitrary conditions.

    Returns True if goal is active AND condition is met.
    """
    goal = goal_load()
    if not goal.get("active"):
        return False
    processed = loop_report.get("processed", 0)
    passed = loop_report.get("passed", 0)
    escalated = loop_report.get("escalated", 0)
    return processed > 0 and passed > 0 and escalated == 0


# ── SPEC freshness (anti-goal-drift) ─────────────────────────────────────────

PENDING_REVIEW_PATH = Path(__file__).resolve().parent.parent / "data" / ".pending_review"


def spec_freshness_check() -> dict[str, Any]:
    """Check modification time of the project spec file.

    Logs spec mtime so the agent/developer can detect staleness.
    Returns dict with path, exists, and mtime_iso fields.
    """
    spec_path_setting = _load_setting("spec_path", "PROJECT.md")
    spec_file = Path(__file__).resolve().parent.parent / spec_path_setting
    info: dict[str, Any] = {
        "spec_path": str(spec_file),
        "exists": spec_file.exists(),
    }
    if spec_file.exists():
        mtime = spec_file.stat().st_mtime
        info["mtime_iso"] = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(mtime)
        )
        info["mtime_ts"] = mtime
    return info


def _load_setting(key: str, default: Any = None) -> Any:
    """Read a single key from settings.json."""
    try:
        sp = Path(__file__).resolve().parent.parent / "data" / "settings.json"
        return json.loads(sp.read_text()).get(key, default)
    except Exception:
        return default


# ── HITL gate — pending review marker ───────────────────────────────────────


def mark_pending_review(beat_result: dict[str, Any]) -> None:
    """Write .pending_review sentinel when tasks escalate.

    The file acts as a signal for external watchers (CI, cron, human).
    Removed automatically when the next beat processes 0 escalated tasks.
    """
    loop = beat_result.get("loop") or {}
    escalated = loop.get("escalated", 0)
    if escalated > 0:
        PENDING_REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
        PENDING_REVIEW_PATH.write_text(
            json.dumps({
                "escalated_count": escalated,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "beat_n": beat_result.get("beat_n", 0),
            }, indent=2) + "\n",
            encoding="utf-8",
        )
    elif PENDING_REVIEW_PATH.exists():
        PENDING_REVIEW_PATH.unlink()
