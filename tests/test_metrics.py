"""Tests for orchestrator/metrics.py — eval result CRUD + aggregation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from orchestrator import metrics


@pytest.fixture()
def temp_metrics_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_metrics.db"
    monkeypatch.setenv("AGENTOS_METRICS_DB_PATH", str(db_path))
    assert metrics.ensure_schema() is True
    yield db_path


class TestRecordMetrics:
    def test_record_and_count(self, temp_metrics_db):
        metrics.record_eval("code-add-function", "answer", 9.0, True)
        metrics.record_eval("direct-greeting", "answer", 8.0, True)
        m = metrics.get_metrics(since_hours=24)
        assert m["total"] == 2
        assert m["passed"] == 2

    def test_record_failure(self, temp_metrics_db):
        metrics.record_eval("code-fix-pytest", "answer", 2.0, False)
        m = metrics.get_metrics(since_hours=24)
        assert m["total"] == 1
        assert m["passed"] == 0

    def test_empty_db(self, temp_metrics_db):
        m = metrics.get_metrics(since_hours=24)
        assert m["total"] == 0
        assert m["pass_rate"] == 0.0


class TestReliabilityScore:
    def test_single_run(self, temp_metrics_db):
        metrics.record_eval("direct-health", "answer", 10.0, True)
        assert metrics.reliability_score("direct-health") == 1.0

    def test_stable_scores(self, temp_metrics_db):
        for _ in range(3):
            metrics.record_eval("direct-greeting", "answer", 9.0, True)
        assert metrics.reliability_score("direct-greeting") > 0.9


class TestValidityScore:
    def test_validity_all_pass(self, temp_metrics_db):
        metrics.record_eval("code-add-function", "answer", 9.0, True)
        metrics.record_eval("direct-greeting", "answer", 10.0, True)
        assert metrics.validity_score() == 1.0

    def test_validity_mixed(self, temp_metrics_db):
        metrics.record_eval("code-add-function", "answer", 10.0, True)
        metrics.record_eval("code-fix-pytest", "answer", 2.0, False)
        assert 0.4 <= metrics.validity_score() <= 0.6
