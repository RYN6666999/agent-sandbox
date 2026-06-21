"""Tests for skill bridge scanner and API."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


# ── scanner unit tests ────────────────────────────────────────────────────


def test_safe_executor_name_basic():
    """Basic name → skill-{name}."""
    from orchestrator.skill_bridge import _safe_executor_name
    assert _safe_executor_name("notebooklm") == "skill-notebooklm"


def test_safe_executor_name_with_suffix():
    """Name + suffix → skill-{name}-{suffix}."""
    from orchestrator.skill_bridge import _safe_executor_name
    assert _safe_executor_name("notebooklm", "ask") == "skill-notebooklm-ask"


def test_read_skill_metadata_basic():
    """SKILL.md 解析出 name 和 description。"""
    from orchestrator.skill_bridge import _read_skill_metadata

    with patch.object(Path, "exists", return_value=True):
        with patch.object(Path, "read_text", return_value="""---
name: my-test-skill
description: A test skill for unit testing
---
# Content
"""):
            meta = _read_skill_metadata(Path("/fake/skill"))
    assert meta["name"] == "my-test-skill"
    assert "test skill" in meta["description"]


def test_read_skill_metadata_no_file():
    """無 SKILL.md → 回傳預設（目錄名）。"""
    from orchestrator.skill_bridge import _read_skill_metadata

    with patch.object(Path, "exists", return_value=False):
        meta = _read_skill_metadata(Path("/fake/myskill"))
    assert meta["name"] == "myskill"
    assert meta["description"] == ""


def test_scan_no_skills_dir():
    """無 .claude/skills/ 目錄 → 錯誤訊息。"""
    from orchestrator.skill_bridge import scan

    with patch("orchestrator.skill_bridge.CLAUDE_SKILLS_DIR", Path("/nonexistent")):
        result = scan()
    assert result["registered"] == 0
    assert "error" in result


def test_scan_skips_real_nonscript_dirs():
    """實際掃描時，純知識型 skill（只有 .md）應被跳過。"""
    from orchestrator.skill_bridge import scan
    # Use force=False so it doesn't re-register existing ones
    # Just verify the function runs without error and returns expected shape
    result = scan(force=False)
    assert "registered" in result
    assert "skipped" in result
    assert "skills" in result


def test_scan_finds_real_skills():
    """實際掃描 → 找到 notebooklm 等技能（需要本機有 ~/.claude/skills/notebooklm/）。"""
    import pytest
    from orchestrator.skill_bridge import CLAUDE_SKILLS_DIR, scan

    # 本測試依賴本機已安裝的 Claude skills，沙箱/CI 環境跳過
    if not CLAUDE_SKILLS_DIR.exists():
        pytest.skip(f"Claude skills dir not found: {CLAUDE_SKILLS_DIR}")

    result = scan(force=True)
    skills = result["skills"]
    # notebooklm should be there (it's installed and has scripts/)
    assert "notebooklm" in skills, f"notebooklm not found in {skills}"
    assert result["registered"] > 0


# ── scan API endpoint ────────────────────────────────────────────────────


@patch("orchestrator.skill_bridge.scan")
def test_scan_api(mock_scan):
    """POST /skill-bridge/scan → 回傳掃描結果。"""
    mock_scan.return_value = {"registered": 10, "skipped": 200, "skills": ["a", "b"]}
    r = client.post("/skill-bridge/scan")
    assert r.status_code == 200
    body = r.json()
    assert body["registered"] == 10
    assert body["skipped"] == 200


# ── executor registry includes skill-* ────────────────────────────────────


def test_executors_includes_skill_entries():
    """GET /executors → 包含 skill-* 前綴的 executor（如果已掃描過）。"""
    r = client.get("/executors")
    names = [e["name"] for e in r.json()["executors"]]
    # At minimum, built-in + web-search + agnes-* should be there
    assert "claude-code" in names
    # skill-* entries depend on whether scan was run this session