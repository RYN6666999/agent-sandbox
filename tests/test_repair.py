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


# ── _extract_repair_keywords: fingerprint → space-joined keywords ──────────────

def test_repair_keyword_extraction():
    from orchestrator.repair import _extract_repair_keywords

    assert _extract_repair_keywords("tests/test_foo.py::test_bar_baz") == "foo bar baz"
    assert _extract_repair_keywords("tests/test_auth.py::TestLogin::test_timeout") == "auth TestLogin timeout"
    assert _extract_repair_keywords("tests/test_simple.py::test_1") == "simple 1"


# ── _build_prompt with brain context retrieval ─────────────────────────────────

def test_repair_brain_retrieval_in_prompt(monkeypatch, tmp_path):
    from orchestrator.repair import _build_prompt

    fake_entries = [
        {"key": "gene/debugging/off-by-one", "content": "上次修過 off-by-one error"},
        {"key": "gene/debugging/login-timeout", "content": "登入逾時是 timeout 設太短"},
    ]

    def fake_search(query, limit=10):
        return fake_entries

    monkeypatch.setattr("orchestrator.knowledge.search_knowledge", fake_search)

    ctx = {
        "fingerprint": "tests/test_foo.py::test_x",
        "test_file": tmp_path / "test_foo.py",
        "test_code": "def test_x(): pass",
        "sources": [],
        "traceback": "AssertionError",
    }
    ctx["test_file"].write_text("")
    result = _build_prompt(ctx)
    assert "Related past experience" in result
    assert "off-by-one" in result


def test_repair_brain_empty_does_not_break(monkeypatch, tmp_path):
    from orchestrator.repair import _build_prompt

    def fake_search(query, limit=10):
        return []

    monkeypatch.setattr("orchestrator.knowledge.search_knowledge", fake_search)

    ctx = {
        "fingerprint": "tests/test_foo.py::test_x",
        "test_file": tmp_path / "test_foo.py",
        "test_code": "def test_x(): pass",
        "sources": [],
        "traceback": "AssertionError",
    }
    ctx["test_file"].write_text("")
    result = _build_prompt(ctx)
    assert "Related past experience" not in result
    assert "Failing test" in result  # 正常內容不受影響
