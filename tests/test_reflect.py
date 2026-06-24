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
