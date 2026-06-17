"""
Hard red lines. LLM cannot override these. Called after mapping, before return.
Policy mutates a copy of the triple, never the original.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataclasses import dataclass
from contracts.routing_triple import RoutingTriple
from router.rules import TaskType

# Models that run locally (no external API calls)
LOCAL_MODELS = {"ollama-local", "ollama/mistral", "ollama/llama3", "lm-studio"}

# Skills banned from certain task types (red lines)
CAVEMAN_BANNED_TYPES = {TaskType.ARCHITECTURE, TaskType.SUMMARY, TaskType.DANGER}
CAVEMAN_SKILL = "caveman"


@dataclass
class PolicyResult:
    triple: RoutingTriple
    violations: list[str]       # what was forced/overridden
    requires_human_confirm: bool


def enforce(triple: RoutingTriple, task_type: TaskType) -> PolicyResult:
    violations: list[str] = []
    requires_human = False

    model = triple.model
    skills = list(triple.skills)
    mcp_tools = list(triple.mcp_tools)

    # Red line 1: SENSITIVE → force local model (always audit, even if already local)
    if task_type == TaskType.SENSITIVE:
        if model not in LOCAL_MODELS:
            violations.append(f"SENSITIVE: forced model {model!r} → ollama-local")
            model = "ollama-local"
        else:
            violations.append(f"SENSITIVE: confirmed local model {model!r}")
        # Strip all non-local tools
        mcp_tools = [t for t in mcp_tools if "local" in t]
        if set(mcp_tools) != set(triple.mcp_tools):
            violations.append("SENSITIVE: stripped non-local mcp_tools")

    # Red line 2: DANGER → human confirm, remove caveman
    if task_type == TaskType.DANGER:
        requires_human = True
        violations.append("DANGER: human confirmation required")
        if CAVEMAN_SKILL in skills:
            skills.remove(CAVEMAN_SKILL)
            violations.append("DANGER: removed caveman skill")

    # Red line 3: caveman banned on architecture/summary/danger
    if task_type in CAVEMAN_BANNED_TYPES and CAVEMAN_SKILL in skills:
        skills.remove(CAVEMAN_SKILL)
        violations.append(f"{task_type.value}: removed caveman (banned for this task type)")

    enforced = RoutingTriple(
        model=model,
        skills=skills,
        mcp_tools=mcp_tools,
        confidence=triple.confidence,
    )
    return PolicyResult(triple=enforced, violations=violations, requires_human_confirm=requires_human)
