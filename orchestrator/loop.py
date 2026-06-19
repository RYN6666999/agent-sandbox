"""
Loop: single verification cycle. No more automated Maker/Checker loop.

In the new architecture, Scream drives the iteration externally:
  1. Scream plans → POST /task/make → gets output
  2. Scream POST /task/verify → gets verdict (pass/retry/escalate)
  3. Scream decides next step based on verdict

This file now provides `run_verification()` — a single check + decide cycle.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from contracts.task_spec import TaskSpec
from orchestrator.checker import check, CheckResult


def run_verification(spec: TaskSpec, output: str,
                     prev_score: float | None = None,
                     max_rounds: int = 5) -> dict:
    """Single verification cycle: check → decide.

    Returns verdict dict:
      {
        "status": "pass" | "retry" | "escalate",
        "score": float,
        "feedback": str,
        "passed": bool,
        "source": "pytest" | "claude-cli",
      }

    Stop conditions (evaluated here):
      達標停: score >= 7.0
      煞車停: rounds >= max_rounds (caller must track rounds)
      撞線停: score == 0.0 (environment error)
    """
    result: CheckResult = check(spec, output, prev_score=prev_score)

    if result.passed:
        status = "pass"
    elif result.score == 0.0:
        status = "escalate"   # environment error / timeout
    else:
        status = "retry"      # needs improvement

    return {
        "status": status,
        "score": result.score,
        "feedback": result.feedback,
        "passed": result.passed,
        "source": result.source,
        "violations": result.violations,
    }