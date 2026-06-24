"""Tests for upgraded pytest-based checker (steps 2-4)."""
import time
from unittest.mock import patch

import pytest

from orchestrator.checker import (
    CheckResult, PytestResult,
    _extract_code, _is_code_output, _has_pytest_tests,
    run_pytest, check,
)
from contracts.task_spec import TaskSpec


# ── helpers ───────────────────────────────────────────────────────────────────

def make_spec(why: str = "compute something") -> TaskSpec:
    return TaskSpec(
        why=why,
        io_example={"input": "2, 3", "expected_output": "5"},
        taste=[],
        boundaries=[],
        stop_on_metric="correctness",
        max_rounds=3,
    )


GOOD_CODE = """\
def add(a, b):
    return a + b

def test_add():
    assert add(2, 3) == 5
"""

BAD_CODE = """\
def add(a, b):
    return a - b

def test_add():
    assert add(2, 3) == 5
"""

SYNTAX_ERROR_CODE = """\
def add(a, b) return a + b

def test_add():
    assert add(2, 3) == 5
"""


# ── unit: code detection ──────────────────────────────────────────────────────

class TestCodeDetection:
    def test_detects_plain_python(self):
        assert _is_code_output("def foo():\n    return 1")

    def test_detects_fenced_python(self):
        assert _is_code_output("```python\ndef foo():\n    return 1\n```")

    def test_rejects_plain_text(self):
        assert not _is_code_output("This is a summary of the findings.")

    def test_rejects_mention_of_def(self):
        assert not _is_code_output("You should define a function called add.")

    def test_detects_tests(self):
        assert _has_pytest_tests("def test_foo():\n    assert True")

    def test_no_tests_in_impl_only(self):
        assert not _has_pytest_tests("def add(a, b):\n    return a + b")


# ── unit: run_pytest ──────────────────────────────────────────────────────────

class TestRunPytest:
    def test_passing_code(self):
        pr = run_pytest("", GOOD_CODE)
        assert pr.passed is True
        assert pr.failed_count == 0
        assert pr.passed_count == 1
        assert pr.timed_out is False
        assert pr.exit_code == 0

    def test_failing_code(self):
        pr = run_pytest("", BAD_CODE)
        assert pr.passed is False
        assert pr.failed_count >= 1
        assert pr.timed_out is False
        assert pr.exit_code != 0
        assert "assert" in pr.stdout.lower() or "failed" in pr.stdout.lower()

    def test_syntax_error_code(self):
        pr = run_pytest("", SYNTAX_ERROR_CODE)
        assert pr.passed is False
        assert pr.timed_out is False
        # exit_code != 0 (collection error) and error recorded as failed
        assert pr.exit_code != 0
        assert pr.failed_count >= 1  # collection error counted as failure

    def test_timeout(self):
        infinite_code = """\
import time

def test_infinite():
    time.sleep(999)
"""
        pr = run_pytest("", infinite_code, timeout=2)
        assert pr.passed is False
        assert pr.timed_out is True
        assert pr.exit_code == -1

    def test_stdout_truncated(self):
        # Generate large output
        many_tests = "\n".join(
            f"def test_t{i}():\n    assert 1 == 2, 'x' * 200\n"
            for i in range(30)
        )
        pr = run_pytest("", many_tests)
        assert len(pr.stdout) <= 4000


# ── Case A: passing code → check() returns passed=True ───────────────────────

class TestCheckerCaseA:
    def test_passing_pytest(self):
        spec = make_spec()
        result = check(spec, GOOD_CODE)

        assert isinstance(result, CheckResult)
        assert result.passed is True
        assert result.score == 10.0
        assert result.pytest_result is not None
        assert result.pytest_result.failed_count == 0
        assert "[PYTEST]" in result.feedback
        assert "LLM_SCORED" not in result.feedback


# ── Case B: failing code → check() returns passed=False ──────────────────────

class TestCheckerCaseB:
    def test_failing_pytest(self):
        spec = make_spec()
        result = check(spec, BAD_CODE)

        assert result.passed is False
        assert result.score < 7.0
        assert result.pytest_result is not None
        assert result.pytest_result.failed_count >= 1
        # stdout must contain failure info for Maker feedback
        assert "assert" in result.pytest_result.stdout.lower() or \
               "failed" in result.pytest_result.stdout.lower()
        assert "[PYTEST]" in result.feedback


# ── Case C: pytest timeout ────────────────────────────────────────────────────

class TestCheckerCaseC:
    def test_timeout_does_not_raise(self):
        infinite = "def test_inf():\n    import time; time.sleep(999)\n"
        spec = make_spec()

        # Patch PYTEST_TIMEOUT to 2s so test doesn't actually wait 60s
        with patch("orchestrator.checker.PYTEST_TIMEOUT", 2):
            result = check(spec, infinite)

        assert result.passed is False
        assert result.score == 0.0
        assert result.pytest_result is not None
        assert result.pytest_result.timed_out is True
        assert "[PYTEST]" in result.feedback


# ── Claude CLI fallback path (v3: 取代 _llm_score) ───────────────────────────
# v3 重構後 _llm_score 已刪除，文字/無測試程式碼 → _claude_cli_check
# 測試 mock _claude_cli_check 以避免實際呼叫 claude CLI

class TestLlmFallbackMarker:
    def test_text_output_delegates_to_claude_cli(self):
        """Pure text output → falls back to _claude_cli_check (claude-cli source)."""
        from orchestrator.checker import CheckResult as CR
        spec = make_spec(why="Summarize the history of Rome")
        text_output = (
            "Rome was founded in 753 BC. It became a republic and then an empire. "
            "It fell in 476 AD."
        )
        fake = CR(passed=True, score=8.0, feedback="[CLAUDE-CLI] good summary", source="claude-cli")
        with patch("orchestrator.checker._claude_cli_check", return_value=fake):
            result = check(spec, text_output)

        assert result.source == "claude-cli"
        assert result.pytest_result is None

    def test_code_without_tests_delegates_to_claude_cli(self):
        """Code with no def test_* → _claude_cli_check, not pytest."""
        from orchestrator.checker import CheckResult as CR
        spec = make_spec()
        impl_only = "def add(a, b):\n    return a + b\n"

        fake = CR(passed=True, score=7.5, feedback="[CLAUDE-CLI] looks good", source="claude-cli")
        with patch("orchestrator.checker._claude_cli_check", return_value=fake):
            result = check(spec, impl_only)

        assert result.source == "claude-cli"
        assert result.pytest_result is None


# ── Language detection tests ─────────────────────────────────────────────────


class TestLanguageDetection:
    def test_detect_javascript_from_fence(self):
        from orchestrator.checker import _detect_language
        assert _detect_language("```javascript\nconst x = 1;\n```") == "javascript"
        assert _detect_language("```js\nconst x = 1;\n```") == "javascript"

    def test_detect_go_from_fence(self):
        from orchestrator.checker import _detect_language
        assert _detect_language("```go\npackage main\n```") == "go"

    def test_detect_go_from_signature(self):
        from orchestrator.checker import _detect_language
        assert _detect_language("package main\n\nfunc main() {}") == "go"

    def test_detect_javascript_from_signature(self):
        from orchestrator.checker import _detect_language
        assert _detect_language("function add(a, b) { return a + b; }") == "javascript"
        assert _detect_language("const x = require('fs');") == "javascript"

    def test_detect_typescript(self):
        from orchestrator.checker import _detect_language
        assert _detect_language("interface User { name: string; }") == "typescript"

    def test_detect_python_default(self):
        from orchestrator.checker import _detect_language
        assert _detect_language("def add(a, b):\n    return a + b") == "python"

    def test_detect_unknown(self):
        from orchestrator.checker import _detect_language
        assert _detect_language("純文字內容 not code") == "unknown"


# ── JS/Go check tests (mocked) ───────────────────────────────────────────────


class TestJestCheck:
    def test_jest_check_passes(self):
        from orchestrator.checker import _jest_check
        from unittest.mock import patch

        with patch("orchestrator.checker.run_jest") as mock_run:
            from orchestrator.checker import PytestResult
            mock_run.return_value = PytestResult(
                passed=True, exit_code=0, passed_count=3, failed_count=0,
                stdout="Tests: 3 passed, 3 total", timed_out=False,
            )
            result = _jest_check("test('add', () => { expect(1+1).toBe(2); })")

        assert result.passed is True
        assert result.score == 10.0
        assert result.source == "pytest"

    def test_jest_check_fails(self):
        from orchestrator.checker import _jest_check
        from unittest.mock import patch

        with patch("orchestrator.checker.run_jest") as mock_run:
            from orchestrator.checker import PytestResult
            mock_run.return_value = PytestResult(
                passed=False, exit_code=1, passed_count=2, failed_count=1,
                stdout="Tests: 2 passed, 1 failed", timed_out=False,
            )
            result = _jest_check("test('failing', () => { expect(1).toBe(2); })")

        assert result.passed is False
        assert result.score == 2.0

    def test_jest_check_timeout(self):
        from orchestrator.checker import _jest_check
        from unittest.mock import patch

        with patch("orchestrator.checker.run_jest") as mock_run:
            from orchestrator.checker import PytestResult
            mock_run.return_value = PytestResult(
                passed=False, exit_code=-1, passed_count=0, failed_count=0,
                stdout="[jest timed out]", timed_out=True,
            )
            result = _jest_check("slow test")

        assert result.score == 0.0
        assert "timed out" in result.feedback


class TestGoCheck:
    def test_go_check_passes(self):
        from orchestrator.checker import _go_check
        from unittest.mock import patch

        with patch("orchestrator.checker.run_go_test") as mock_run:
            from orchestrator.checker import PytestResult
            mock_run.return_value = PytestResult(
                passed=True, exit_code=0, passed_count=1, failed_count=0,
                stdout="ok  testcheck", timed_out=False,
            )
            result = _go_check("func TestAdd(t *testing.T) { ... }")

        assert result.passed is True
        assert result.score == 10.0
        assert result.source == "pytest"

    def test_go_check_fails(self):
        from orchestrator.checker import _go_check
        from unittest.mock import patch

        with patch("orchestrator.checker.run_go_test") as mock_run:
            from orchestrator.checker import PytestResult
            mock_run.return_value = PytestResult(
                passed=False, exit_code=1, passed_count=0, failed_count=1,
                stdout="FAIL  testcheck", timed_out=False,
            )
            result = _go_check("func TestBroken(t *testing.T) { t.Fail() }")

        assert result.passed is False
        assert result.score == 2.0


# ── Integration: check() dispatches correctly ────────────────────────────────


class TestCheckDispatch:
    def test_python_still_works(self, monkeypatch):
        """Python code should still go through pytest path."""
        from orchestrator.checker import check
        from contracts.task_spec import TaskSpec
        spec = TaskSpec(why="add", io_example={"input": "1,2", "expected_output": "3"},
                        taste=[], boundaries=[], stop_on_metric="quality", max_rounds=1)

        output = "```python\ndef add(a, b): return a + b\n\ndef test_add():\n    assert add(1,2) == 3\n```"

        # Don't mock — just verify it dispatches without error and checks type
        # We mock run_pytest to avoid actual subprocess
        from unittest.mock import patch
        from orchestrator.checker import PytestResult
        with patch("orchestrator.checker.run_pytest") as mock_rp:
            mock_rp.return_value = PytestResult(passed=True, exit_code=0,
                                                passed_count=1, failed_count=0,
                                                stdout="1 passed", timed_out=False)
            result = check(spec, output)

        assert result.source == "pytest"
        mock_rp.assert_called_once()

    def test_javascript_dispatches_to_jest(self, monkeypatch):
        """JS code with test patterns should go through jest path."""
        from orchestrator.checker import check
        from contracts.task_spec import TaskSpec
        spec = TaskSpec(why="js test", io_example={"input": "", "expected_output": "pass"},
                        taste=[], boundaries=[], stop_on_metric="quality", max_rounds=1)

        output = "```javascript\nfunction add(a, b) { return a + b; }\n\ntest('add', () => { expect(add(1,2)).toBe(3); })\n```"

        from unittest.mock import patch
        from orchestrator.checker import PytestResult
        with patch("orchestrator.checker.run_jest") as mock_jest:
            mock_jest.return_value = PytestResult(passed=True, exit_code=0,
                                                  passed_count=1, failed_count=0,
                                                  stdout="Tests: 1 passed", timed_out=False)
            result = check(spec, output)

        # Should not reach the python test check
        assert result.passed is True
        mock_jest.assert_called_once()
