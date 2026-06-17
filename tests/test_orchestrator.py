"""Orchestrator tests. Mock LLM calls — test stop-condition logic only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import patch, MagicMock
from contracts.task_spec import TaskSpec
from orchestrator.checker import check, CheckResult
from orchestrator import blackboard


def make_spec(**kwargs) -> TaskSpec:
    defaults = dict(
        why="build cashflow calculator",
        io_example={"input": "rent=30000", "expected_output": "cashflow=9000"},
        taste=["show breakdown"],
        boundaries=["no tax calculation"],
        stop_on_metric="output contains cashflow figure",
        max_rounds=5,
    )
    return TaskSpec(**{**defaults, **kwargs})


# ── Checker unit tests (no LLM) ──────────────────────────────────────────

def test_checker_keyword_miss_fails_immediately():
    spec = make_spec()
    # output has nothing resembling "cashflow" or "9000"
    result = check(spec, "hello world", prev_score=None)
    assert not result.passed
    assert result.score == 0.0
    assert "missing expected keywords" in result.feedback


def test_checker_boundary_violation_fails():
    spec = make_spec()
    result = check(spec, "cashflow=9000 including tax calculation", prev_score=None)
    assert not result.passed
    assert any("boundary" in v for v in result.violations)


def test_checker_no_progress_detected():
    spec = make_spec()
    # Mock LLM to return score 6.0 (below 7.0 threshold)
    with patch("orchestrator.checker._llm_score", return_value=(6.0, "needs improvement")):
        result1 = check(spec, "cashflow=9000", prev_score=5.8)
    # delta = 6.0 - 5.8 = 0.2 < 0.5 → no_progress flag
    assert "[no progress]" in result1.feedback
    assert not result1.passed


def test_checker_pass_when_score_high():
    spec = make_spec()
    with patch("orchestrator.checker._llm_score", return_value=(8.5, "looks good")):
        result = check(spec, "cashflow=9000 breakdown: rent 30000 mortgage 18000", prev_score=None)
    assert result.passed
    assert result.score == 8.5


# ── Loop stop-condition tests (mock maker + checker) ─────────────────────

def _mock_make(score_sequence: list[float]):
    """Returns a make() mock + checker mock that yields scores in sequence."""
    call_count = {"n": 0}

    def fake_make(spec, feedback="", round_n=1, on_token=None):
        return f"cashflow=9000 round={round_n}"

    def fake_check(spec, output, prev_score=None):
        idx = call_count["n"]
        call_count["n"] += 1
        score = score_sequence[min(idx, len(score_sequence) - 1)]
        passed = score >= 7.0
        return CheckResult(passed=passed, score=score, feedback=f"score={score}")

    return fake_make, fake_check


def test_loop_passes_on_high_score():
    from orchestrator.loop import run
    spec = make_spec(max_rounds=5)
    fake_make, fake_check = _mock_make([8.0])
    with patch("orchestrator.loop.make", fake_make), \
         patch("orchestrator.loop.check", fake_check):
        result = run(spec)
    assert result["status"] == "done"
    assert result["rounds"] == 1


def test_loop_escalates_on_max_rounds():
    from orchestrator.loop import run
    spec = make_spec(max_rounds=3)
    fake_make, fake_check = _mock_make([4.0, 4.2, 4.3])  # never reaches 7.0
    with patch("orchestrator.loop.make", fake_make), \
         patch("orchestrator.loop.check", fake_check):
        result = run(spec)
    assert result["status"] == "escalate"


def test_loop_escalates_on_no_progress_streak():
    from orchestrator.loop import run
    spec = make_spec(max_rounds=10)
    # score barely moves → no_progress_streak hits 2
    fake_make, fake_check = _mock_make([5.0, 5.1, 5.2])
    with patch("orchestrator.loop.make", fake_make), \
         patch("orchestrator.loop.check", fake_check):
        result = run(spec)
    assert result["status"] == "escalate"


def test_loop_retries_before_passing():
    from orchestrator.loop import run
    spec = make_spec(max_rounds=5)
    fake_make, fake_check = _mock_make([4.0, 5.5, 8.0])  # pass on round 3
    with patch("orchestrator.loop.make", fake_make), \
         patch("orchestrator.loop.check", fake_check):
        result = run(spec)
    assert result["status"] == "done"
    assert result["rounds"] == 3


# ── Blackboard ────────────────────────────────────────────────────────────

def test_blackboard_write_read():
    blackboard.write("test_entry", {"value": 42})
    data = blackboard.read_latest("test_entry")
    assert data is not None
    assert data["value"] == 42
