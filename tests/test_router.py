"""Router unit tests. Policy red lines must hold regardless of LLM output."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from router.rules import rule_match, TaskType
from router.mapping import get_triple
from router.policy import enforce
from router.skill_injector import build_system_prompt
from router import route


# --- Stage-1 rules ---

def test_rule_sensitive():
    hit = rule_match("my password is stored in this file")
    assert hit is not None
    assert hit.task_type == TaskType.SENSITIVE

def test_rule_danger():
    hit = rule_match("delete all records from the database")
    assert hit is not None
    assert hit.task_type == TaskType.DANGER

def test_rule_summary():
    hit = rule_match("summarize this 50-page document")
    assert hit is not None
    assert hit.task_type == TaskType.SUMMARY

def test_rule_architecture():
    hit = rule_match("design the system architecture for the auth service")
    assert hit is not None
    assert hit.task_type == TaskType.ARCHITECTURE

def test_rule_no_match():
    hit = rule_match("xyzzyx zork blorp")
    assert hit is None


# --- Policy red lines ---

def test_policy_sensitive_forces_local():
    triple = get_triple(TaskType.SENSITIVE)
    result = enforce(triple, TaskType.SENSITIVE)
    assert result.triple.model == "ollama-local", "SENSITIVE must use local model"
    assert result.violations, "must log the override"

def test_policy_sensitive_strips_egress_tools():
    triple = get_triple(TaskType.SENSITIVE)
    result = enforce(triple, TaskType.SENSITIVE)
    for tool in result.triple.mcp_tools:
        assert "local" in tool, f"SENSITIVE must not have non-local tool: {tool}"

def test_policy_danger_requires_human():
    triple = get_triple(TaskType.DANGER)
    result = enforce(triple, TaskType.DANGER)
    assert result.requires_human_confirm is True

def test_policy_caveman_banned_on_architecture():
    from contracts.routing_triple import RoutingTriple
    triple = RoutingTriple(model="claude-sonnet", skills=["align", "caveman"], mcp_tools=[], confidence=0.9)
    result = enforce(triple, TaskType.ARCHITECTURE)
    assert "caveman" not in result.triple.skills

def test_policy_caveman_banned_on_summary():
    from contracts.routing_triple import RoutingTriple
    triple = RoutingTriple(model="gemini-flash", skills=["caveman"], mcp_tools=[], confidence=0.9)
    result = enforce(triple, TaskType.SUMMARY)
    assert "caveman" not in result.triple.skills

def test_policy_caveman_allowed_on_highfreq():
    from contracts.routing_triple import RoutingTriple
    triple = RoutingTriple(model="agnes", skills=["ponytail", "caveman"], mcp_tools=[], confidence=0.9)
    result = enforce(triple, TaskType.HIGH_FREQ)
    assert "caveman" in result.triple.skills


# --- Skill injection ---

def test_skill_injection_claude_no_inject():
    prompt = build_system_prompt(["ponytail", "caveman"], "claude-sonnet", "base")
    assert "PONYTAIL" not in prompt
    assert prompt == "base"

def test_skill_injection_non_claude_injects():
    prompt = build_system_prompt(["ponytail"], "agnes", "base")
    assert "PONYTAIL" in prompt
    assert "lazy senior" in prompt

def test_skill_injection_unknown_skill_ignored():
    prompt = build_system_prompt(["nonexistent-skill"], "agnes", "base")
    assert prompt == "base"


# --- End-to-end route() (no LLM call needed for rule-hit cases) ---

def test_route_sensitive_e2e():
    result = route("my api token is leaked in this file")
    assert result.triple.model == "ollama-local"
    assert result.requires_human_confirm is False  # sensitive ≠ danger

def test_route_danger_e2e():
    result = route("drop the production database")
    assert result.requires_human_confirm is True

def test_route_summary_no_caveman():
    result = route("summarize this document into 3 bullet points")
    assert "caveman" not in result.triple.skills
