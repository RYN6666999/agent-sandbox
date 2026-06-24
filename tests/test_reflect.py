"""Tests for orchestrator/reflect.py — reflection engine rules."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from orchestrator import reflect, metrics


class TestReflect:
    def test_no_reflections_on_empty_metrics(self):
        rs = reflect.reflect_recent(n_hours=24)
        assert isinstance(rs, list)

    def test_should_not_propose_empty(self):
        assert reflect.should_propose({"total": 0, "pass_rate": 0.0, "by_scenario": {}}) is False

    def test_build_proposal_empty(self):
        p = reflect.build_proposal([])
        assert "No improvements" in p.title

    def test_build_proposal_with_reflections(self):
        rs = [
            reflect.Reflection(
                trigger="low_score", symptom="test", category="code",
                suggested_change="fix it", severity="critical",
            ),
        ]
        p = reflect.build_proposal(rs)
        assert p.reflections == rs
        assert p.autofix_possible is False  # no "threshold" in suggestion


def test_brain_reflections_returns_list():
    """_brain_reflections should always return a list."""
    from orchestrator.reflect import _brain_reflections
    from unittest.mock import patch

    with patch("orchestrator.knowledge.search_knowledge", return_value=[]):
        refs = _brain_reflections()
    assert isinstance(refs, list)


def test_brain_reflections_returns_warning_when_frequent():
    """3+ escalation records → warning reflection."""
    from orchestrator.reflect import _brain_reflections
    from unittest.mock import patch

    fake_results = [
        {"key": "gene/workflow/escalate-1", "content": "撞線記錄 1"},
        {"key": "gene/workflow/escalate-2", "content": "撞線記錄 2"},
        {"key": "gene/workflow/escalate-3", "content": "撞線記錄 3"},
    ]
    with patch("orchestrator.knowledge.search_knowledge", return_value=fake_results):
        refs = _brain_reflections()
    assert len(refs) >= 1
    assert refs[0].severity == "warning"
