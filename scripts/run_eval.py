"""Run eval scenarios against AgentOS routing pipeline and record metrics.

This is the heart of the OPTIMIZATION.md closed loop. It:
1. Loads scenarios from eval/scenarios.json
2. Routes each through the classifier + safety + clarify gates
3. Records results via metrics.record_eval()
4. Reports pass/fail per category

Safe to run frequently — most scenarios don't need LLM calls
(clarify/sensitive/danger are rule-based).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator import metrics
from router.classifier import routing_intent
from orchestrator.safety import is_dangerous
from orchestrator.clarify import needs_clarification

SCENARIOS_PATH = Path(__file__).parent.parent / "eval" / "scenarios.json"


def load_scenarios() -> list[dict]:
    raw = SCENARIOS_PATH.read_text(encoding="utf-8")
    return json.loads(raw)


def run_scenario(scenario: dict) -> dict:
    """Run one scenario through the routing pipeline and return eval result."""
    task = scenario["task"]
    expected_routing = scenario["expected_routing"]
    expected_stop = scenario["expected_stop"]
    min_score = scenario.get("min_score", 7.0)
    scenario_id = scenario["id"]

    # Stage 1: Safety gate (rule-based, no LLM)
    danger_result = is_dangerous(task)
    danger = danger_result[0] if isinstance(danger_result, tuple) else danger_result
    if danger:
        actual_routing = "answer"
        actual_stop = "escalate"
        score = 10.0 if expected_stop == "escalate" else 0.0
        passed = score >= min_score
        return {"scenario_id": scenario_id, "routing": actual_routing,
                "score": score, "passed": passed, "gate": "safety"}

    # Stage 2: Clarify gate (rule-based, no LLM)
    clar = needs_clarification(task)
    if clar:
        actual_routing = "unclear"
        # 先判斷 safety 再判斷 clarify：clarify 期望的 stop 是 pass
        actual_stop = "pass"
        score = 10.0 if expected_routing == "unclear" else 0.0
        passed = score >= min_score
        return {"scenario_id": scenario_id, "routing": actual_routing,
                "score": score, "passed": passed, "gate": "clarify"}

    # Stage 3: Router (rule-based classifier, no LLM)
    intent = routing_intent(task)
    actual_routing = intent.get("intent", "answer") if intent else "answer"

    if actual_routing == expected_routing:
        score = 10.0
    else:
        score = 0.0
    passed = score >= min_score

    return {"scenario_id": scenario_id, "routing": actual_routing,
            "score": score, "passed": passed, "gate": "router"}


def run_all() -> dict:
    """Run all scenarios and record to metrics. Returns summary."""
    metrics.ensure_schema()
    scenarios = load_scenarios()
    results = []
    passes = 0
    fails = 0

    for s in scenarios:
        r = run_scenario(s)
        results.append(r)
        metrics.record_eval(r["scenario_id"], r["routing"],
                            r["score"], r["passed"])
        if r["passed"]:
            passes += 1
        else:
            fails += 1

    # Group by category
    by_category = {}
    for s, r in zip(scenarios, results):
        cat = s["category"]
        if cat not in by_category:
            by_category[cat] = {"total": 0, "passed": 0}
        by_category[cat]["total"] += 1
        if r["passed"]:
            by_category[cat]["passed"] += 1

    return {
        "total": len(scenarios),
        "passed": passes,
        "failed": fails,
        "by_category": by_category,
        "results": results,
    }


if __name__ == "__main__":
    summary = run_all()
    print(f"Eval complete: {summary['passed']}/{summary['total']} passed")
    for cat, stats in summary["by_category"].items():
        print(f"  {cat}: {stats['passed']}/{stats['total']}")
    for r in summary["results"]:
        status = "✅" if r["passed"] else "❌"
        print(f"  {status} {r['scenario_id']:30s} gate={r['gate']:8s} "
              f"route={r['routing']:8s} score={r['score']}")
