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


# ── Checker unit tests (v3: text/code → _claude_cli_check) ───────────────

def test_checker_text_output_delegates_to_claude_cli():
    """v3: 文字輸出（非程式碼）→ _claude_cli_check，score 由 claude-cli 決定。"""
    from orchestrator.checker import CheckResult as CR
    spec = make_spec()
    fake = CR(passed=False, score=2.0, feedback="[CLAUDE-CLI] incomplete", source="claude-cli")
    with patch("orchestrator.checker._claude_cli_check", return_value=fake):
        result = check(spec, "hello world", prev_score=None)
    assert not result.passed
    assert result.source == "claude-cli"


def test_checker_code_without_tests_delegates_to_claude_cli():
    """v3: 有程式碼但無測試 → _claude_cli_check（不直接跑 pytest）。"""
    from orchestrator.checker import CheckResult as CR
    spec = make_spec()
    impl_only = "cashflow=9000 including tax calculation"
    fake = CR(passed=False, score=3.0, feedback="[CLAUDE-CLI] boundary check", source="claude-cli")
    with patch("orchestrator.checker._claude_cli_check", return_value=fake):
        result = check(spec, impl_only, prev_score=None)
    assert not result.passed
    assert result.source == "claude-cli"


def test_checker_claude_cli_pass():
    """v3: claude-cli 回傳 score >= 7.0 → passed=True。"""
    from orchestrator.checker import CheckResult as CR
    spec = make_spec()
    fake = CR(passed=True, score=8.5, feedback="[CLAUDE-CLI] looks good", source="claude-cli")
    with patch("orchestrator.checker._claude_cli_check", return_value=fake):
        result = check(spec, "cashflow=9000 breakdown: rent 30000", prev_score=None)
    assert result.passed
    assert result.score == 8.5


def test_checker_claude_cli_fail():
    """v3: claude-cli 回傳 score < 7.0 → passed=False。"""
    from orchestrator.checker import CheckResult as CR
    spec = make_spec()
    fake = CR(passed=False, score=6.0, feedback="[CLAUDE-CLI] needs improvement", source="claude-cli")
    with patch("orchestrator.checker._claude_cli_check", return_value=fake):
        result = check(spec, "cashflow=9000", prev_score=5.8)
    assert not result.passed
    assert result.score == 6.0


# ── run_verification stop-condition tests (v3 loop) ───────────────────────
# v3 的 loop.py 只有 run_verification()，沒有 run()。
# run_verification 做一次 check → 回傳 pass/retry/escalate。

def test_verification_passes_on_high_score():
    """pytest pass (score=10.0) → status=pass。"""
    from orchestrator.checker import CheckResult as CR
    spec = make_spec(max_rounds=5)
    fake = CR(passed=True, score=10.0, feedback="[PYTEST] 1 passed", source="pytest")
    with patch("orchestrator.loop.check", return_value=fake):
        from orchestrator.loop import run_verification
        result = run_verification(spec, "def test_x(): assert True")
    assert result["status"] == "pass"
    assert result["passed"] is True


def test_verification_retries_on_low_score():
    """pytest fail (score=2.0) → status=retry。"""
    from orchestrator.checker import CheckResult as CR
    spec = make_spec(max_rounds=5)
    fake = CR(passed=False, score=2.0, feedback="[PYTEST] 1 failed", source="pytest")
    with patch("orchestrator.loop.check", return_value=fake):
        from orchestrator.loop import run_verification
        result = run_verification(spec, "bad code")
    assert result["status"] == "retry"
    assert result["passed"] is False


def test_verification_escalates_on_zero_score():
    """score=0.0（timeout/env error）→ status=escalate。"""
    from orchestrator.checker import CheckResult as CR
    spec = make_spec(max_rounds=5)
    fake = CR(passed=False, score=0.0, feedback="[PYTEST] timed out", source="pytest")
    with patch("orchestrator.loop.check", return_value=fake):
        from orchestrator.loop import run_verification
        result = run_verification(spec, "")
    assert result["status"] == "escalate"


# ── Blackboard ────────────────────────────────────────────────────────────

def test_blackboard_write_read():
    blackboard.write("test_entry", {"value": 42})
    data = blackboard.read_latest("test_entry")
    assert data is not None
    assert data["value"] == 42


# ── Executor Registry ──────────────────────────────────────────────────────

def test_executor_registry_has_claude_code():
    """claude-code should be pre-registered with correct config."""
    from orchestrator import executor_registry
    defn = executor_registry.get("claude-code")
    assert defn is not None
    assert defn["binary"] == "claude"
    assert defn["type"] == "subprocess"
    assert defn["default_model"] == "claude-sonnet-4-6"


def test_executor_registry_list_contains_claude_code():
    from orchestrator import executor_registry
    all_ = executor_registry.list_all()
    names = [e["name"] for e in all_]
    assert "claude-code" in names


def test_executor_registry_get_unknown_returns_none():
    from orchestrator import executor_registry
    assert executor_registry.get("nonexistent") is None


def test_executor_registry_register_and_retrieve():
    from orchestrator import executor_registry
    executor_registry.register({
        "name": "test-exec",
        "binary": "/usr/bin/echo",
        "timeout": 10,
    })
    defn = executor_registry.get("test-exec")
    assert defn is not None
    assert defn["binary"] == "/usr/bin/echo"


def test_executor_registry_super_engine_type():
    """super-engine type executor can be registered with args field."""
    from orchestrator import executor_registry
    executor_registry.register({
        "name": "super-engine-test",
        "binary": "node",
        "args": ["ask.ts", "--provider", "genspark", "--prompt"],
        "timeout": 120,
        "type": "super-engine",
    })
    defn = executor_registry.get("super-engine-test")
    assert defn is not None
    assert defn["type"] == "super-engine"
    assert "args" in defn
    assert "--prompt" in defn["args"]
