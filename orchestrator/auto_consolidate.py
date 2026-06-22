"""Auto-Consolidate (Session D): turn a verification verdict into a brain gene.

After a verification completes, extract one experience from the verdict and
write it to the knowledge base under gene/. This is the self-growth mechanism:
the system remembers what passed and what blocked it, across sessions.

Fires on terminal outcomes only — pass (what worked) and escalate (what blocked,
for the human). "retry" is mid-flight, not yet a lesson, so it is skipped to
keep the brain free of transient noise.

ponytail: thin adapter over consolidate_experiences. No new storage, no new
extraction LLM — run_verification's verdict already carries score/feedback/source.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from contracts.task_spec import TaskSpec
from orchestrator.knowledge import consolidate_experiences

logger = logging.getLogger(__name__)

# Outcomes worth remembering. "retry" is transient — not yet a lesson.
CONSOLIDATE_STATUSES = {"pass", "escalate"}


def verdict_to_experience(spec: TaskSpec, verdict: dict[str, Any]) -> dict[str, Any] | None:
    """Map a run_verification verdict to one consolidate experience.

    Returns None when the outcome is not worth remembering (e.g. "retry").
    """
    status = verdict.get("status")
    if status not in CONSOLIDATE_STATUSES:
        return None

    score = verdict.get("score", 0.0)
    source = verdict.get("source") or "unknown"
    task = (spec.why or "").strip()

    if status == "pass":
        exp_type = "pattern"
        what = f"任務通過驗收 (score {score}, via {source}): {task}"
        fix = ""
    else:  # escalate
        exp_type = "bug-fix"
        what = f"任務撞線需人介入 (score {score}, via {source}): {task}"
        fix = verdict.get("feedback") or ""

    return {
        "domain": "workflow",
        "type": exp_type,
        "what": what,
        "fix": fix,
        "tags": [status, source],
    }


def auto_consolidate(spec: TaskSpec, verdict: dict[str, Any]) -> list[dict[str, Any]]:
    """Best-effort: extract a gene from the verdict and write it to the brain.

    Never raises — a consolidation failure must not break verification. Returns
    the genes written (empty list if skipped or on failure).
    """
    exp = verdict_to_experience(spec, verdict)
    if exp is None:
        return []
    try:
        return consolidate_experiences([exp])
    except Exception as e:  # best-effort: log, never propagate into verification
        logger.warning("auto_consolidate failed (verification unaffected): %s", e)
        return []


if __name__ == "__main__":
    # ponytail self-check: the routing logic that matters, no framework.
    from contracts.task_spec import TaskSpec as _T

    s = _T(why="x", io_example={"input": "x", "expected_output": ""},
           taste=[], boundaries=[], stop_on_metric="quality", max_rounds=1)
    assert verdict_to_experience(s, {"status": "retry", "score": 4.0}) is None
    p = verdict_to_experience(s, {"status": "pass", "score": 10.0, "source": "pytest"})
    assert p["type"] == "pattern" and p["fix"] == "" and "pass" in p["tags"]
    e = verdict_to_experience(s, {"status": "escalate", "score": 0.0, "feedback": "boom"})
    assert e["type"] == "bug-fix" and e["fix"] == "boom"
    print("auto_consolidate self-check OK")
