"""
Checker: validates Scream output against TaskSpec stop conditions.

In the v3 architecture, Claude CLI is the Checker. AgentOS wraps it:

Check pipeline:
  1. Detect if output is Python code with embedded tests
     → Yes: run pytest in subprocess (objective pass/fail)
     → Code without tests or pure text: delegate to Claude CLI via executor_registry

No LLM fallback scoring path — the old litellm-based scoring is removed.
"""
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from contracts.task_spec import TaskSpec
from orchestrator import executor_registry

PYTEST_TIMEOUT = 60          # seconds before pytest subprocess is killed
STDOUT_MAX = 4000            # chars kept from pytest output


# ── data structures ──────────────────────────────────────────────────────────

@dataclass
class PytestResult:
    passed: bool
    exit_code: int
    passed_count: int
    failed_count: int
    stdout: str              # truncated to STDOUT_MAX
    timed_out: bool
    error: Optional[str] = None


@dataclass
class CheckResult:
    passed: bool
    score: float             # 10.0 (pytest pass) | 2.0 (pytest fail) | 0.0 (error)
    feedback: str
    violations: list[str] = field(default_factory=list)
    pytest_result: Optional[PytestResult] = None
    source: str = ""         # "pytest" | "claude-cli"


# ── code detection helpers ────────────────────────────────────────────────────

_CODE_PATTERN = re.compile(r'^\s*(def |class |import |from \S+ import )', re.MULTILINE)
_TEST_PATTERN = re.compile(r'^\s*def test_\w+', re.MULTILINE)
_FENCE_PATTERN = re.compile(r'```(?:python)?\n(.*?)```', re.DOTALL)


def _extract_code(output: str) -> str:
    """Pull code from ```python``` fences; fall back to raw text.
    Also strips common web-LLM UI noise (Gemini, GenSpark prefixes/labels).
    """
    text = output.strip()
    for prefix in ["Gemini 說了", "Gemini說", "Gemini said"]:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    for lang in ["Python", "python", "javascript", "typescript", "bash"]:
        if text.startswith(lang + "def ") or text.startswith(lang + "class "):
            text = text[len(lang):]
    blocks = _FENCE_PATTERN.findall(text)
    return '\n\n'.join(blocks) if blocks else text


def _is_code_output(output: str) -> bool:
    """True only when output clearly contains Python code (line-start patterns)."""
    return bool(_CODE_PATTERN.search(_extract_code(output)))


def _has_pytest_tests(code: str) -> bool:
    """True when code contains at least one pytest-style test function."""
    return bool(_TEST_PATTERN.search(code))


# ── pytest runner ─────────────────────────────────────────────────────────────

def _parse_counts(stdout: str) -> tuple[int, int]:
    """Return (passed_count, failed_count) from pytest -q output."""
    passed = 0
    failed = 0
    m = re.search(r'(\d+) passed', stdout)
    if m:
        passed = int(m.group(1))
    m = re.search(r'(\d+) failed', stdout)
    if m:
        failed = int(m.group(1))
    if failed == 0 and passed == 0:
        if re.search(r'(ERROR collecting|SyntaxError|ImportError|error)', stdout, re.IGNORECASE):
            failed = 1
    return passed, failed


def run_pytest(code: str, test_code: str, timeout: int = PYTEST_TIMEOUT) -> PytestResult:
    """
    Write code + test_code to a temp dir and run `pytest -q`.

    Returns PytestResult; never raises.
    """
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            if code.strip():
                (tmp / "solution.py").write_text(code, encoding="utf-8")
            (tmp / "test_solution.py").write_text(test_code, encoding="utf-8")

            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", "test_solution.py"],
                    capture_output=True, text=True, cwd=tmpdir, timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                return PytestResult(passed=False, exit_code=-1,
                                    passed_count=0, failed_count=0,
                                    stdout="[pytest timed out]", timed_out=True)

            raw_out = (proc.stdout + proc.stderr)[:STDOUT_MAX]
            passed_count, failed_count = _parse_counts(proc.stdout + proc.stderr)
            ok = proc.returncode == 0 and failed_count == 0

            return PytestResult(passed=ok, exit_code=proc.returncode,
                                passed_count=passed_count, failed_count=failed_count,
                                stdout=raw_out, timed_out=False)

    except Exception as exc:
        return PytestResult(passed=False, exit_code=-1,
                            passed_count=0, failed_count=0,
                            stdout=str(exc)[:STDOUT_MAX], timed_out=False, error=str(exc))


# ── main checker ──────────────────────────────────────────────────────────────

def check(spec: TaskSpec, output: str, prev_score: float | None = None) -> CheckResult:
    """Validate output against spec. No LLM fallback — pure pytest or Claude CLI."""
    extracted = _extract_code(output)
    is_code = _is_code_output(output)
    has_tests = _has_pytest_tests(extracted)

    if is_code and has_tests:
        return _pytest_check(extracted)

    # Code without tests, or text output → delegate to Claude CLI
    return _claude_cli_check(spec, output)


def _pytest_check(code_with_tests: str) -> CheckResult:
    """Run pytest; map results to CheckResult."""
    pr = run_pytest("", code_with_tests)

    if pr.timed_out:
        return CheckResult(passed=False, score=0.0,
                           feedback="[PYTEST] timed out",
                           pytest_result=pr, source="pytest")

    if pr.passed:
        return CheckResult(passed=True, score=10.0,
                           feedback=f"[PYTEST] {pr.passed_count} passed, 0 failed",
                           pytest_result=pr, source="pytest")

    summary = pr.stdout[:500].strip()
    return CheckResult(passed=False, score=2.0,
                       feedback=f"[PYTEST] {pr.failed_count} failed, {pr.passed_count} passed\n{summary}",
                       pytest_result=pr, source="pytest")


def _claude_cli_check(spec: TaskSpec, output: str) -> CheckResult:
    """Delegate verification to Claude CLI for non-pytest outputs.

    Claude CLI evaluates code quality, correctness, and provides feedback.
    """
    reason = "no tests found in output" if _is_code_output(output) else "text output"
    prompt = (
        f"You are a strict evaluator. Score the output 0-10 based on: "
        f"{spec.stop_on_metric or 'correctness and completeness'}\n\n"
        f"Task: {spec.why}\n"
        f"Expected: {spec.io_example.get('expected_output', '')}\n\n"
        f"Output to evaluate:\n{output[:4000]}\n\n"
        "Respond with JSON only: "
        '{"score": <0-10>, "feedback": "<one sentence on what to improve>"}'
    )

    try:
        if executor_registry.get("claude-code"):
            result = executor_registry.run("claude-code", prompt, timeout=120)
        else:
            return CheckResult(passed=False, score=0.0,
                               feedback=f"[CLAUDE-CLI] claude-code executor not registered [{reason}]",
                               source="claude-cli")

        raw = result.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        import json
        data = json.loads(raw)
        score = float(data["score"])
        feedback = data.get("feedback", "")
        passed = score >= 7.0
        return CheckResult(passed=passed, score=score,
                           feedback=f"[CLAUDE-CLI | {reason}] {feedback}",
                           source="claude-cli")
    except Exception as e:
        return CheckResult(passed=False, score=0.0,
                           feedback=f"[CLAUDE-CLI | {reason}] error: {e}",
                           source="claude-cli")