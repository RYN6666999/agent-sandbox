"""Reflection engine: analyze traces and propose improvements.

Part of the OPTIMIZATION.md closed loop. Takes metrics from metrics.py and
decision_log traces, produces structured proposals for prompt/routing/threshold
changes.

Initial implementation is rule-based (no LLM) to keep it deterministic and cheap.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestrator import metrics


@dataclass
class Reflection:
    trigger: str  # "low_score" | "repeated_escalation" | "wrong_routing"
    symptom: str
    category: str  # scenario category from scenarios.json
    suggested_change: str
    severity: str = "info"  # "info" | "warning" | "critical"


@dataclass
class Proposal:
    title: str
    reflections: list[Reflection] = field(default_factory=list)
    autofix_possible: bool = False
    autofix_path: str = ""


def _brain_reflections() -> list[Reflection]:
    """Check brain for recurring failure patterns across recent tasks.
    
    Rule: if brain has 3+ "撞線" or "escalate" records, flag as warning.
    """
    try:
        from orchestrator import knowledge
        results = knowledge.search_knowledge("撞線", limit=10)
        # Also search English terms
        eng_results = knowledge.search_knowledge("escalate", limit=5)
        all_results = results + eng_results
        # Deduplicate by key
        seen_keys = set()
        unique = []
        for r in all_results:
            k = r.get("key", "")
            if k not in seen_keys:
                seen_keys.add(k)
                unique.append(r)
        
        if len(unique) >= 3:
            return [Reflection(
                trigger="repeated_escalation",
                symptom=f"Brain shows {len(unique)} escalation gene records — recurring failure pattern detected",
                category="*",
                suggested_change="Review escalated tasks for common root causes; consider adjusting stop thresholds or routing rules",
                severity="warning",
            )]
        if len(unique) >= 1:
            return [Reflection(
                trigger="repeated_escalation",
                symptom=f"Brain has {len(unique)} escalation record(s) — monitor for pattern development",
                category="*",
                suggested_change="Monitor escalation frequency; no action needed yet",
                severity="info",
            )]
    except Exception:
        pass
    return []


def reflect_recent(n_hours: int = 24, metrics_dict: dict | None = None) -> list[Reflection]:
    """Analyze recent metrics and return reflections.
    
    Args:
        n_hours: lookback window in hours
        metrics_dict: optional pre-fetched metrics (avoids extra DB read)
    """
    reflections: list[Reflection] = []
    m = metrics_dict if metrics_dict is not None else metrics.get_metrics(since_hours=n_hours)

    # Rule 1: Any scenario with avg_score < 3.0 is critical
    for scenario_id, info in m.get("by_scenario", {}).items():
        if info.get("avg_score", 10.0) < 3.0 and info.get("runs", 0) >= 2:
            reflections.append(Reflection(
                trigger="low_score",
                symptom=f"Scenario '{scenario_id}' avg score {info['avg_score']} over {info['runs']} runs",
                category=scenario_id,
                suggested_change="Review routing rules or prompt instructions for this scenario type",
                severity="critical",
            ))

    # Rule 2: repeated escalation signals
    # (Requires trace from decision_log; placeholder for V1)
    # Will be extended when traces are fed in.

    # Rule 3: Low pass rate overall
    if m.get("total", 0) >= 5 and m.get("pass_rate", 1.0) < 0.5:
        reflections.append(Reflection(
            trigger="low_score",
            symptom=f"Overall pass rate {m['pass_rate']} is below 0.5",
            category="*",
            suggested_change="Consider adjusting stop thresholds or review prompt quality",
            severity="warning",
        ))

    # Brain-based reflections
    brain_refs = _brain_reflections()
    reflections.extend(brain_refs)
    
    return reflections


def should_propose(metrics_dict: dict | None = None) -> bool:
    """Return True if there are enough signals to build a proposal."""
    if metrics_dict is None:
        metrics_dict = metrics.get_metrics(since_hours=24)
    reflections = reflect_recent(metrics_dict=metrics_dict)
    if not reflections:
        return False
    critical_count = sum(1 for r in reflections if r.severity == "critical")
    return critical_count >= 1 or len(reflections) >= 2


def build_proposal(reflections: list[Reflection] | None = None) -> Proposal:
    """Aggregate reflections into a Proposal."""
    if reflections is None:
        reflections = reflect_recent()
    if not reflections:
        return Proposal(title="No improvements needed at this time")

    # Group by severity
    criticals = [r for r in reflections if r.severity == "critical"]
    title = f"Auto-detected {len(criticals)} critical + {len(reflections) - len(criticals)} warning signals"

    # Check if any reflection can be auto-fixed
    autofix = any("threshold" in r.suggested_change.lower() for r in reflections)

    return Proposal(
        title=title,
        reflections=reflections,
        autofix_possible=autofix,
        autofix_path="",
    )
