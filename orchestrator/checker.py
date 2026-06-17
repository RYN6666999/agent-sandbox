"""
Checker: validates Maker output against TaskSpec stop conditions.

Check pipeline (in order):
  1. Detect if output is Python code with embedded tests
     → If yes: run actual pytest in subprocess (real pass/fail)
     → If code without tests: LLM fallback (marked as LLM_SCORED)
     → If pure text: LLM fallback (marked as LLM_SCORED)
  2. keyword / boundary hard checks apply only on the LLM path

Pass threshold (pytest path): exit_code == 0 and failed_count == 0
Pass threshold (LLM path):    llm_score >= 7.0
score mapping: 10.0 (pytest pass) | 2.0 (pytest fail) | 0.0 (timeout/error)
               so score never misleads loop.py's no_progress calculation.
"""
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import litellm
from contracts.task_spec import TaskSpec
from orchestrator.model_registry import resolve as _resolve

_DEFAULT_CHECKER_MODEL = "gemini-flash"
_DEFAULT_CHECKER_FALLBACKS = ["agnes"]
_CHECKER_SETTINGS_PATH = Path(__file__).parent.parent / "data" / "settings.json"


def _checker_model_and_fallbacks() -> tuple[str, list[str]]:
    try:
        s = json.loads(_CHECKER_SETTINGS_PATH.read_text())
        return (
            s.get("checker_model", _DEFAULT_CHECKER_MODEL),
            s.get("checker_fallbacks", _DEFAULT_CHECKER_FALLBACKS),
        )
    except Exception:
        return _DEFAULT_CHECKER_MODEL, _DEFAULT_CHECKER_FALLBACKS

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
    score: float             # 0.0–10.0, kept for loop.py no_progress calc
    feedback: str
    violations: list[str] = field(default_factory=list)
    pytest_result: Optional[PytestResult] = None


# ── code detection helpers ────────────────────────────────────────────────────

_CODE_PATTERN = re.compile(
    r'^\s*(def |class |import |from \S+ import )',
    re.MULTILINE,
)
_TEST_PATTERN = re.compile(r'^\s*def test_\w+', re.MULTILINE)
_FENCE_PATTERN = re.compile(r'```(?:python)?\n(.*?)```', re.DOTALL)


def _extract_code(output: str) -> str:
    """Pull code from ```python``` fences; fall back to raw text."""
    blocks = _FENCE_PATTERN.findall(output)
    return '\n\n'.join(blocks) if blocks else output


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
    # collection/syntax errors: exit non-zero but 0 passed, 0 failed
    # treat as 1 failure so passed stays False
    if failed == 0 and passed == 0:
        if re.search(r'(ERROR collecting|SyntaxError|ImportError|error)', stdout, re.IGNORECASE):
            failed = 1
    return passed, failed


def run_pytest(code: str, test_code: str, timeout: int = PYTEST_TIMEOUT) -> PytestResult:
    """
    Write code + test_code to a temp dir and run `pytest -q`.

    - code: implementation (empty string if tests are self-contained)
    - test_code: the test file content (must have def test_* functions)
    - Returns PytestResult; never raises.
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
                    capture_output=True,
                    text=True,
                    cwd=tmpdir,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                return PytestResult(
                    passed=False, exit_code=-1,
                    passed_count=0, failed_count=0,
                    stdout="[pytest timed out]",
                    timed_out=True,
                )

            raw_out = (proc.stdout + proc.stderr)[:STDOUT_MAX]
            passed_count, failed_count = _parse_counts(proc.stdout + proc.stderr)
            ok = proc.returncode == 0 and failed_count == 0

            return PytestResult(
                passed=ok,
                exit_code=proc.returncode,
                passed_count=passed_count,
                failed_count=failed_count,
                stdout=raw_out,
                timed_out=False,
            )

    except Exception as exc:
        return PytestResult(
            passed=False, exit_code=-1,
            passed_count=0, failed_count=0,
            stdout=str(exc)[:STDOUT_MAX],
            timed_out=False,
            error=str(exc),
        )


# ── main checker ──────────────────────────────────────────────────────────────

def check(spec: TaskSpec, output: str, prev_score: float | None = None) -> CheckResult:
    extracted = _extract_code(output)
    is_code = _is_code_output(output)
    has_tests = _has_pytest_tests(extracted)

    if is_code and has_tests:
        return _pytest_check(extracted)

    # ── LLM path (text output, or code without tests) ────────────────────────
    reason = "no tests found in output" if is_code else "text output"
    return _llm_check(spec, output, prev_score, llm_reason=reason)


def _pytest_check(code_with_tests: str) -> CheckResult:
    """Run pytest; map results to CheckResult. score is always 10 or < 7."""
    pr = run_pytest("", code_with_tests)   # all code+tests in one file

    if pr.timed_out:
        return CheckResult(
            passed=False, score=0.0,
            feedback="[PYTEST] timed out",
            pytest_result=pr,
        )

    if pr.passed:
        return CheckResult(
            passed=True, score=10.0,
            feedback=f"[PYTEST] {pr.passed_count} passed, 0 failed",
            pytest_result=pr,
        )

    # Any failure: score=2.0 (always below 7.0 threshold)
    summary = pr.stdout[:500].strip()
    return CheckResult(
        passed=False, score=2.0,
        feedback=f"[PYTEST] {pr.failed_count} failed, {pr.passed_count} passed\n{summary}",
        pytest_result=pr,
    )


def _llm_check(
    spec: TaskSpec, output: str,
    prev_score: float | None,
    llm_reason: str,
) -> CheckResult:
    """Original LLM scoring path — always marked [LLM_SCORED]."""
    violations: list[str] = []

    # keyword check
    expected = str(spec.io_example.get("expected_output", ""))
    keywords = [w.strip() for w in expected.replace("=", " ").split() if len(w) > 2]
    missing = [kw for kw in keywords if kw.lower() not in output.lower()]
    if missing:
        violations.append(f"missing expected keywords: {missing}")

    # boundary check
    for boundary in spec.boundaries:
        if boundary.lower().startswith("no "):
            forbidden = boundary[3:].strip().lower()
            if forbidden and forbidden in output.lower():
                violations.append(f"boundary crossed: {boundary!r}")

    if violations:
        return CheckResult(
            passed=False, score=0.0,
            feedback=f"[LLM_SCORED | {llm_reason}] Hard check failed: {'; '.join(violations)}",
            violations=violations,
        )

    score, llm_feedback = _llm_score(spec, output)
    no_progress = prev_score is not None and (score - prev_score) < 0.5
    passed = score >= 7.0 and not no_progress

    return CheckResult(
        passed=passed, score=score,
        feedback=f"[LLM_SCORED | {llm_reason}] {llm_feedback}" + (" [no progress]" if no_progress else ""),
        violations=[],
    )


def _llm_score(spec: TaskSpec, output: str) -> tuple[float, str]:
    metric = spec.stop_on_metric or "correctness and completeness"
    prompt = (
        f"You are a strict evaluator. Score the output 0-10 based on: {metric}\n\n"
        f"Task: {spec.why}\n"
        f"Expected: {spec.io_example.get('expected_output', '')}\n\n"
        f"Output to evaluate:\n{output[:2000]}\n\n"
        "Respond with JSON only: "
        '{"score": <0-10>, "feedback": "<one sentence on what to improve>"}'
    )
    import json
    checker_model, checker_fallbacks = _checker_model_and_fallbacks()
    for alias in [checker_model] + checker_fallbacks:
        try:
            params = _resolve(alias)
            resp = litellm.completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.0,
                **params,
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            return float(data["score"]), data.get("feedback", "")
        except (litellm.RateLimitError, litellm.BadRequestError) as e:
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
                continue
            return 5.0, f"checker LLM error: {e}"
        except Exception as e:
            return 5.0, f"checker LLM error: {e}"
    return 5.0, "checker: all models rate-limited"
