"""Main route() entry point."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from contracts.routing_triple import RoutingTriple
from router.rules import rule_match, TaskType
from router.mapping import get_triple
from router.classifier import llm_classify_detailed
from router.policy import enforce, PolicyResult
from orchestrator import decision_log


def route(
    task: str,
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    round_n: int | None = None,
) -> PolicyResult:
    """2-stage router. Returns PolicyResult with enforced RoutingTriple."""
    hit = rule_match(task)
    matched_keyword = None
    classifier_model = None
    fallback_reason = None
    retry_count = 0

    if hit:
        task_type = hit.task_type
        confidence = hit.confidence
        matched_keyword = hit.matched_keyword
        decision_source = "rule"
    else:
        cls = llm_classify_detailed(task)
        task_type = cls.task_type
        confidence = cls.confidence
        classifier_model = cls.classifier_model
        fallback_reason = cls.fallback_reason
        retry_count = cls.retry_count
        decision_source = cls.source

    mapped = get_triple(task_type)
    pre_policy = RoutingTriple(
        model=mapped.model,
        skills=list(mapped.skills),
        mcp_tools=list(mapped.mcp_tools),
        confidence=confidence,
    )
    result = enforce(pre_policy, task_type)
    final = result.triple
    policy_changed = (
        pre_policy.model != final.model
        or pre_policy.skills != final.skills
        or pre_policy.mcp_tools != final.mcp_tools
    )

    if request_id and session_id:
        decision_log.record_execution_route(
            request_id=request_id,
            session_id=session_id,
            round_n=round_n,
            decision=task_type.value,
            decision_source=decision_source,
            matched_keyword=matched_keyword,
            confidence=confidence,
            classifier_model=classifier_model,
            fallback_reason=fallback_reason,
            pre_policy_model=pre_policy.model,
            pre_policy_skills=pre_policy.skills,
            pre_policy_tools=pre_policy.mcp_tools,
            final_model=final.model,
            final_skills=final.skills,
            final_tools=final.mcp_tools,
            policy_applied=True,
            policy_changed=policy_changed,
            requires_human_confirm=result.requires_human_confirm,
            violations=result.violations,
            details={
                "task": task,
                "task_type": task_type.value,
                "retry_count": retry_count,
            },
        )

    return result
