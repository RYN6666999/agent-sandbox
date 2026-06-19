"""
Loop: single verification cycle. v3 角色映射。

v3 角色定位：
  Scream = 計劃 + 執行 — 自己 call LLM、寫 code、判斷交付，不經 AgentOS maker proxy
  Claude CLI = 驗收 (Checker only) — 不寫 code，只跑 pytest + 審查
  AgentOS = 純 Action 回圈層（零智力基礎設施）
  Opus 4.8 (GenSpark) = 顧問 — 不是 maker，不進產線
  Gemini (super-engine) = 小雜工

This file is the AgentOS-level verification action: a single check + decide cycle.
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