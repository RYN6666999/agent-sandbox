"""Doc-drift guards — make the recurring "請幫我對齊文檔" loop impossible.

Two classes of drift kept coming back because nothing guarded them:

1. The file-map in README/PROJECT pointed at modules that got renamed/deleted.
2. A hardcoded global test count ("348 passed") went stale on every PR.

These tests run in the existing CI (pytest), so the drift fails loudly instead
of waiting for a human to notice and ask an agent to re-align. The fix for #2 is
to NOT write the number at all — this test forbids re-introducing it.

ponytail: the best alignment is the alignment you never have to do again.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


# ── #1: file-map modules must exist ────────────────────────────────────────

# Precise single-file references (orchestrator/<x>.py, tests/test_<x>.py).
# Fuzzy shorthand like "agnes-analyze/image/video.py" is intentionally not matched.
_MODULE_REF = re.compile(r"\b(orchestrator/\w+\.py|tests/test_\w+\.py|router/\w+\.py)\b")


def test_doc_file_map_points_at_real_files():
    docs = ["README.md", "PROJECT.md", ".scream-code/handoff-next-session.md"]
    missing: list[str] = []
    for doc in docs:
        for ref in set(_MODULE_REF.findall(_read(doc))):
            if not (ROOT / ref).exists():
                missing.append(f"{doc} -> {ref}")
    assert not missing, "docs reference files that don't exist:\n  " + "\n  ".join(missing)


# ── #2: no hardcoded global test count in current-state docs ───────────────

# Matches the treadmill patterns: "348 passed", "348 tests", "21 個測試檔".
# PROJECT.md / BUGFIX.md are excluded — they carry dated historical logs
# ("248 passed" from a 2026-06-21 debug session) that must stay frozen.
_COUNT = re.compile(r"\d+\s*(passed|tests\b|個測試檔)")
_CURRENT_STATE_DOCS = [
    "README.md",
    "task_plan.md",
    "OPTIMIZATION.md",
    ".scream-code/handoff-next-session.md",
]


def test_no_hardcoded_test_count_in_current_docs():
    offenders: list[str] = []
    for doc in _CURRENT_STATE_DOCS:
        for m in _COUNT.finditer(_read(doc)):
            offenders.append(f"{doc}: …{m.group(0)!r}…")
    assert not offenders, (
        "hardcoded test count re-introduced (it WILL drift). "
        "Say '跑 pytest 看數' instead:\n  " + "\n  ".join(offenders)
    )


if __name__ == "__main__":
    test_doc_file_map_points_at_real_files()
    test_no_hardcoded_test_count_in_current_docs()
    print("docs-drift guards OK")
