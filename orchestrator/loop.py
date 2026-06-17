"""
Maker/Checker loop via LangGraph StateGraph.

State machine:
  START → maker → checker → {
    "pass"     → END  (deliver)
    "retry"    → maker (with feedback)
    "escalate" → END  (human needed)
  }

Stop conditions (from TaskSpec, set at align time):
  達標停: checker score >= 7.0
  煞車停: rounds >= max_rounds  OR  score_delta < 0.5 for 2 consecutive rounds
  撞線停: budget exceeded or env error → escalate
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import threading
from typing import Annotated, TypedDict, Callable
from langgraph.graph import StateGraph, END
from contracts.task_spec import TaskSpec
from orchestrator.maker import make
from orchestrator.checker import check, CheckResult

# ponytail: threading.local so concurrent sessions don't clobber each other's callbacks
_local = threading.local()


class LoopState(TypedDict):
    spec: dict                  # TaskSpec.model_dump()
    request_id: str | None
    session_id: str | None
    round_n: int
    output: str
    feedback: str
    prev_score: float | None
    no_progress_streak: int
    status: str                 # "running" | "done" | "escalate"
    history: list[dict]


# ── nodes ──────────────────────────────────────────────────────────────────

def maker_node(state: LoopState) -> LoopState:
    spec = TaskSpec(**state["spec"])
    on_round_start = getattr(_local, "on_round_start", None)
    on_token = getattr(_local, "on_token", None)
    if on_round_start:
        on_round_start(state["round_n"])
    if state.get("request_id") and state.get("session_id"):
        output = make(spec, feedback=state["feedback"], round_n=state["round_n"],
                      on_token=on_token,
                      request_id=state.get("request_id"),
                      session_id=state.get("session_id"))
    else:
        output = make(spec, feedback=state["feedback"], round_n=state["round_n"],
                      on_token=on_token)
    return {**state, "output": output}


def checker_node(state: LoopState) -> LoopState:
    spec = TaskSpec(**state["spec"])
    result: CheckResult = check(spec, state["output"], prev_score=state["prev_score"])

    no_progress_streak = state["no_progress_streak"]
    if not result.passed and state["prev_score"] is not None:
        delta = result.score - (state["prev_score"] or 0)
        no_progress_streak = no_progress_streak + 1 if delta < 0.5 else 0
    else:
        no_progress_streak = 0

    entry = {
        "round": state["round_n"],
        "score": result.score,
        "passed": result.passed,
        "feedback": result.feedback,
    }
    # Determine next status
    if result.passed:
        status = "done"
    elif state["round_n"] >= spec.max_rounds or no_progress_streak >= 2:
        status = "escalate"
    else:
        status = "running"

    return {
        **state,
        "prev_score": result.score,
        "feedback": result.feedback,
        "no_progress_streak": no_progress_streak,
        "round_n": state["round_n"] + 1,
        "status": status,
        "history": state["history"] + [entry],
    }


# ── routing ─────────────────────────────────────────────────────────────────

def route_after_checker(state: LoopState) -> str:
    return state["status"]   # "done" | "running" | "escalate"


# ── graph ───────────────────────────────────────────────────────────────────

def build_graph():
    g = StateGraph(LoopState)
    g.add_node("maker", maker_node)
    g.add_node("checker", checker_node)

    g.set_entry_point("maker")
    g.add_edge("maker", "checker")
    g.add_conditional_edges(
        "checker",
        route_after_checker,
        {"done": END, "running": "maker", "escalate": END},
    )
    return g.compile()


# ── entrypoint ──────────────────────────────────────────────────────────────

def run(spec: TaskSpec,
        on_token: Callable[[str], None] | None = None,
        on_round_start: Callable[[int], None] | None = None,
        request_id: str | None = None,
        session_id: str | None = None) -> dict:
    """Run Maker/Checker loop. Returns final state dict."""
    _local.on_token = on_token
    _local.on_round_start = on_round_start

    graph = build_graph()
    initial: LoopState = {
        "spec": spec.model_dump(),
        "request_id": request_id,
        "session_id": session_id,
        "round_n": 1,
        "output": "",
        "feedback": "",
        "prev_score": None,
        "no_progress_streak": 0,
        "status": "running",
        "history": [],
    }
    try:
        final = graph.invoke(initial)
    finally:
        _local.on_token = None
        _local.on_round_start = None

    result = {
        "status": final["status"],
        "output": final["output"],
        "rounds": final["round_n"] - 1,
        "final_score": final["prev_score"],
        "history": final["history"],
    }
    return result
