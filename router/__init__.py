"""Main route() entry point."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from contracts.routing_triple import RoutingTriple
from router.rules import rule_match, TaskType
from router.mapping import get_triple
from router.classifier import llm_classify
from router.policy import enforce, PolicyResult


def route(task: str) -> PolicyResult:
    """2-stage router. Returns PolicyResult with enforced RoutingTriple."""
    hit = rule_match(task)
    if hit:
        task_type = hit.task_type
        triple = get_triple(task_type)
        triple = RoutingTriple(model=triple.model, skills=triple.skills,
                               mcp_tools=triple.mcp_tools, confidence=hit.confidence)
    else:
        task_type, confidence = llm_classify(task)
        triple = get_triple(task_type)
        triple = RoutingTriple(model=triple.model, skills=triple.skills,
                               mcp_tools=triple.mcp_tools, confidence=confidence)

    return enforce(triple, task_type)
