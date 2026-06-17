"""TaskType → RoutingTriple mapping table."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from contracts.routing_triple import RoutingTriple
from router.rules import TaskType

# ponytail: this is the single source of truth for model/skill/tool assignment.
# Change here propagates everywhere. Adding a new TaskType requires a new row.
MAPPING: dict[TaskType, RoutingTriple] = {
    TaskType.ARCHITECTURE: RoutingTriple(
        model="claude-sonnet",
        skills=["align"],
        mcp_tools=["file", "execute", "search"],
        confidence=0.9,
    ),
    TaskType.FEATURE: RoutingTriple(
        model="agnes",          # local first, fallback to sonnet via litellm
        skills=["ponytail"],
        mcp_tools=["file", "execute"],
        confidence=0.8,
    ),
    TaskType.TEST: RoutingTriple(
        model="agnes",
        skills=["ponytail"],
        mcp_tools=["file", "execute"],
        confidence=0.8,
    ),
    TaskType.HIGH_FREQ: RoutingTriple(
        model="agnes",
        skills=["ponytail", "caveman"],
        mcp_tools=["file"],
        confidence=0.9,
    ),
    TaskType.SUMMARY: RoutingTriple(
        model="gemini-flash",
        skills=[],              # caveman banned on summary (red line)
        mcp_tools=["file"],
        confidence=0.9,
    ),
    TaskType.SENSITIVE: RoutingTriple(
        model="ollama-local",   # policy will enforce this — no egress
        skills=[],
        mcp_tools=["local-file"],
        confidence=1.0,
    ),
    TaskType.DANGER: RoutingTriple(
        model="claude-sonnet",  # policy will add human-confirm gate
        skills=[],              # caveman banned on danger (red line)
        mcp_tools=[],
        confidence=1.0,
    ),
}


def get_triple(task_type: TaskType) -> RoutingTriple:
    triple = MAPPING.get(task_type)
    if triple is None:
        # Safe default: cheap model, no tools
        return RoutingTriple(model="agnes", skills=[], mcp_tools=[], confidence=0.3)
    return triple
