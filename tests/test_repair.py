"""orchestrator/repair.py — pure-logic guards (no network).

The real fix is exercised end-to-end against a live model offline (see the
session log / repair.py __main__ smoke). Here we lock the safety + parsing logic
that must hold even when the model misbehaves.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from orchestrator import repair

REPO = Path(__file__).resolve().parent.parent


# ── _safe_target: never edit tests / escape repo / touch venv / invent files ──

def test_safe_target_accepts_real_source():
    assert repair._safe_target("orchestrator/safety.py", REPO) is not None

def test_safe_target_refuses_test_file():
    assert repair._safe_target("tests/test_safety.py", REPO) is None

def test_safe_target_refuses_path_escape():
    assert repair._safe_target("../../../etc/passwd", REPO) is None

def test_safe_target_refuses_nonexistent():
    assert repair._safe_target("orchestrator/does_not_exist.py", REPO) is None

def test_safe_target_refuses_non_python():
    assert repair._safe_target("README.md", REPO) is None


# ── local_import_sources: find code under test, exclude tests ─────────────────

def test_local_imports_resolves_repo_module():
    srcs = repair.local_import_sources("from orchestrator.safety import is_dangerous\n", REPO)
    assert any(p.name == "safety.py" for p in srcs)

def test_local_imports_excludes_test_files(tmp_path):
    # a test-looking import target must not be returned as editable source
    (tmp_path / "test_thing.py").write_text("x=1")
    srcs = repair.local_import_sources("import test_thing\n", tmp_path)
    assert srcs == []


# ── parse_proposal: extract path + complete file, strip leaked label ──────────

def test_parse_proposal_extracts_path_and_code():
    raw = "# FILE: mod.py\n```python\ndef f():\n    return 1\n```"
    path, content = repair.parse_proposal(raw)
    assert path == "mod.py"
    assert content == "def f():\n    return 1"

def test_parse_proposal_strips_leaked_file_label():
    raw = "```python\n# FILE: mod.py\ndef f():\n    return 1\n```"
    # _FILE_RE still finds the path inside; the label line is stripped from content
    path, content = repair.parse_proposal(raw)
    assert path == "mod.py"
    assert not content.startswith("# FILE:")
    assert content.startswith("def f():")

def test_parse_proposal_rejects_malformed():
    assert repair.parse_proposal("here is some prose, no code block")[0] is None
