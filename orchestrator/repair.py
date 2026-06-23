"""Real self-repair — actually fix a failing repo test by editing repo source.

The inspector→runner→checker loop only graded self-contained code blobs; it never
read or wrote repo files, so a repo test failure could only ever escalate. This
closes that gap:

  gather context (failing test + its local-import source files + traceback)
  -> LLM proposes a corrected source file ("# FILE: <path>" + full contents)
  -> write it to the repo, run the ACTUAL failing test, then the FULL suite
  -> keep iff the test passes AND nothing else regressed; otherwise REVERT.

Red lines (enforced here, not trusted to the model):
  - never edit a test file or anything outside repo_root / inside .venv
  - never leave the repo dirty: every failure path restores originals
  - the test's assertions are the oracle; we only touch source under test

Code-exec note: this writes model output to a repo file and runs pytest. That is
the whole point of a self-repair tool, but it only runs on tasks the inspector
raised, edits are confined + reverted on any regression, and the full-suite gate
catches a fix that "passes the one test" by breaking others.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

import litellm  # noqa: E402
from orchestrator.model_registry import resolve as _resolve  # noqa: E402

PYTEST_TIMEOUT = 120
MAX_CONTEXT_FILES = 5
MAX_FILE_BYTES = 16_000

_SYS = (
    "You fix a buggy Python SOURCE file so a given pytest test passes. "
    "The test is the oracle: it is CORRECT, do not change it. Fix the source. "
    "Output exactly ONE block:\n"
    "# FILE: <relative/path/to/source.py>\n```python\n<the COMPLETE corrected file>\n```\n"
    "No prose. The path must be one of the source files shown (never a test file)."
)
_FILE_RE = re.compile(r"#\s*FILE:\s*(\S+)")
_CODE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)
_FAILED_RE = re.compile(r"^FAILED\s+(\S+\.py::\S+)", re.MULTILINE)


@dataclass
class RepairResult:
    status: str                 # "passed" | "escalated"
    rounds: int = 0
    cost_usd: float = 0.0
    target: str = ""
    feedback: str = ""
    history: list[str] = field(default_factory=list)


def _is_test_path(p: Path) -> bool:
    return p.name.startswith("test_") or p.name.endswith("_test.py") or "tests" in p.parts


def _safe_target(path_str: str, repo_root: Path) -> Path | None:
    """Resolve a model-proposed path to a real, editable repo source file, or None."""
    try:
        p = (repo_root / path_str).resolve()
        p.relative_to(repo_root.resolve())          # confined to repo
    except (ValueError, OSError):
        return None
    if ".venv" in p.parts or not p.suffix == ".py" or _is_test_path(p) or not p.exists():
        return None
    return p


def local_import_sources(test_code: str, repo_root: Path) -> list[Path]:
    """Repo .py files the test imports (the code under test). Excludes tests/stdlib."""
    found: list[Path] = []
    seen: set[Path] = set()
    for m in re.finditer(r"^\s*(?:from|import)\s+([a-zA-Z_][\w.]*)", test_code, re.M):
        dotted = m.group(1)
        rel = dotted.replace(".", "/")
        for cand in (repo_root / f"{rel}.py", repo_root / rel / "__init__.py",
                     repo_root / f"{dotted.split('.')[0]}.py"):
            if cand.exists() and not _is_test_path(cand) and cand not in seen:
                seen.add(cand)
                found.append(cand)
    return found[:MAX_CONTEXT_FILES]


def _run_pytest(target: str, repo_root: Path) -> tuple[bool, str]:
    """Run `pytest <target>` in repo_root. Returns (passed, output)."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", target, "--tb=short", "-q", "-rf"],
            capture_output=True, text=True, cwd=str(repo_root), timeout=PYTEST_TIMEOUT,
        )
        return proc.returncode == 0, (proc.stdout + proc.stderr)[-3000:]
    except subprocess.TimeoutExpired:
        return False, "[pytest timed out]"


def gather_context(fingerprint: str, repo_root: Path) -> dict[str, Any] | None:
    test_file = repo_root / fingerprint.split("::", 1)[0]
    if not test_file.exists():
        return None
    test_code = test_file.read_text(encoding="utf-8")
    sources = local_import_sources(test_code, repo_root)
    if not sources:
        return None  # nothing editable to fix — bug is in the test itself
    _, tb = _run_pytest(fingerprint, repo_root)
    return {"test_file": test_file, "test_code": test_code, "sources": sources, "traceback": tb}


def _build_prompt(ctx: dict, extra_feedback: str = "") -> str:
    parts = [f"Failing test: make `pytest {ctx['test_file'].name}` green.\n",
             "TEST (do NOT change):\n```python\n" + ctx["test_code"] + "\n```\n"]
    for src in ctx["sources"]:
        rel = src.relative_to(_repo_of(src))
        body = src.read_text(encoding="utf-8")[:MAX_FILE_BYTES]
        parts.append(f"SOURCE {rel}:\n```python\n{body}\n```\n")
    parts.append("pytest output:\n" + ctx["traceback"][-1500:] + "\n")
    if extra_feedback:
        parts.append("\nYour previous fix did not work:\n" + extra_feedback + "\n")
    return "\n".join(parts)


def _repo_of(p: Path) -> Path:
    # walk up to the dir containing pyproject.toml (repo root); fallback parent
    for d in p.resolve().parents:
        if (d / "pyproject.toml").exists():
            return d
    return p.parent


def _propose(model: str, prompt: str) -> tuple[str | None, str, float]:
    """Returns (rel_path, file_content, cost_usd) or (None, raw, cost)."""
    kw = _resolve(model)
    resp = litellm.completion(
        messages=[{"role": "system", "content": _SYS}, {"role": "user", "content": prompt}],
        max_tokens=1500, temperature=0.1, timeout=90, **kw,
    )
    raw = resp.choices[0].message.content or ""
    try:
        cost = float(litellm.completion_cost(resp) or 0.0)
    except Exception:
        cost = 0.0
    rel, content = parse_proposal(raw)
    if rel is None:
        return None, raw, cost
    return rel, content, cost


def parse_proposal(raw: str) -> tuple[str | None, str]:
    """Pure: extract (rel_path, complete_file_content) from a model proposal.

    Expects '# FILE: <path>' plus one ```python block. Strips a leaked '# FILE:'
    line if the model put it inside the code block. Returns (None, raw) if malformed.
    """
    pm, cm = _FILE_RE.search(raw), _CODE_RE.search(raw)
    if not (pm and cm):
        return None, raw
    content = re.sub(r"^#\s*FILE:.*\n", "", cm.group(1).strip())
    return pm.group(1).strip(), content


def repair_task(fingerprint: str, *, model: str, repo_root: Path, max_rounds: int = 3) -> RepairResult:
    """Try to fix the failing test by editing repo source. Repo left clean either way."""
    ctx = gather_context(fingerprint, repo_root)
    if ctx is None:
        return RepairResult(status="escalated", feedback="no editable source import found "
                            "(failure is in the test itself, or test file missing)")
    res = RepairResult(status="escalated", target="")
    feedback = ""
    for rnd in range(1, max_rounds + 1):
        res.rounds = rnd
        try:
            rel, content, cost = _propose(model, _build_prompt(ctx, feedback))
        except Exception as exc:
            res.history.append(f"r{rnd}: propose error {exc}")
            continue
        res.cost_usd += cost
        if rel is None:
            feedback = "Output must be: '# FILE: <path>' then one ```python block."
            res.history.append(f"r{rnd}: unparseable output")
            continue
        target = _safe_target(rel, repo_root)
        if target is None:
            feedback = f"'{rel}' is not an editable repo source file. Pick one of the SOURCE files."
            res.history.append(f"r{rnd}: bad target {rel}")
            continue
        res.target = str(target.relative_to(repo_root))
        original = target.read_text(encoding="utf-8")
        target.write_text(content, encoding="utf-8")
        test_ok, test_out = _run_pytest(fingerprint, repo_root)
        if not test_ok:
            target.write_text(original, encoding="utf-8")            # revert
            feedback = "Test still fails:\n" + test_out[-1200:]
            res.history.append(f"r{rnd}: test still red")
            continue
        suite_ok, suite_out = _run_pytest("", repo_root)             # full-suite regression gate
        if not suite_ok:
            broken = ", ".join(_FAILED_RE.findall(suite_out)[:5])
            target.write_text(original, encoding="utf-8")            # revert
            feedback = f"Your fix passed the target test but BROKE others: {broken}. Fix without regressions."
            res.history.append(f"r{rnd}: regressed suite")
            continue
        res.status = "passed"                                        # kept: test green, suite green
        res.feedback = f"fixed {res.target} in round {rnd}"
        res.history.append(f"r{rnd}: PASSED")
        return res
    res.feedback = feedback or "max rounds exhausted"
    return res


if __name__ == "__main__":
    # smoke: regex + safety guards (no LLM, no network)
    repo = Path(__file__).parent.parent
    assert _safe_target("orchestrator/repair.py", repo) is not None
    assert _safe_target("tests/test_repair.py", repo) is None        # test file refused
    assert _safe_target("../../etc/passwd", repo) is None            # escape refused
    assert _safe_target("nope.py", repo) is None                     # nonexistent refused
    assert local_import_sources("from orchestrator.safety import is_dangerous\n", repo)
    print("repair self-check OK")
