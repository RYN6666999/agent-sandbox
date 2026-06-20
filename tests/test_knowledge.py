"""知識庫 CRUD + FTS 搜尋測試。

遵循 test_decision_log.py 的 pattern：用 tmp_path + monkeypatch 模擬 DB，
不寫入真實檔案。
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator import knowledge


@pytest.fixture()
def temp_knowledge_db(tmp_path, monkeypatch):
    db_path = tmp_path / "knowledge.db"
    monkeypatch.setenv("AGENTOS_KNOWLEDGE_DB_PATH", str(db_path))
    # Disable gbrain for unit tests (no network calls)
    fake_settings = tmp_path / "settings.json"
    fake_settings.write_text(json.dumps({"gbrain": {"enabled": False}}), encoding="utf-8")
    monkeypatch.setattr(knowledge, "_load_gbrain_config", lambda: {"url": "", "enabled": False, "token": ""})
    assert knowledge.ensure_schema() is True
    yield db_path


def _rows(db_path: Path, sql: str, params: tuple = ()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _one(db_path: Path, sql: str, params: tuple = ()):
    rows = _rows(db_path, sql, params)
    assert rows, f"no rows for query: {sql}"
    return rows[0]


# ── write_knowledge ──────────────────────────────────────────────────────────


def test_write_creates_entry(temp_knowledge_db):
    entry_id = knowledge.write_knowledge(
        "project/svelte-setup",
        "Need Node 18+ and pnpm for Svelte 5",
        metadata={"author": "opus"},
    )
    assert len(entry_id) == 16  # UUID hex[:16]

    row = _one(temp_knowledge_db, "SELECT * FROM entries WHERE id = ?", (entry_id,))
    assert row["key"] == "project/svelte-setup"
    assert row["content"] == "Need Node 18+ and pnpm for Svelte 5"
    meta = json.loads(row["metadata"])
    assert meta["author"] == "opus"


def test_write_without_metadata(temp_knowledge_db):
    entry_id = knowledge.write_knowledge("test/key", "just content")
    row = _one(temp_knowledge_db, "SELECT * FROM entries WHERE id = ?", (entry_id,))
    assert row["key"] == "test/key"
    assert row["content"] == "just content"
    assert json.loads(row["metadata"]) == {}


def test_write_same_key_appends(temp_knowledge_db):
    """相同 key 寫入兩次應該產生兩筆紀錄（不覆蓋）。"""
    id1 = knowledge.write_knowledge("topic/foo", "first version")
    id2 = knowledge.write_knowledge("topic/foo", "second version")

    assert id1 != id2
    rows = _rows(temp_knowledge_db, "SELECT * FROM entries WHERE key = 'topic/foo' ORDER BY created_at")
    assert len(rows) == 2
    assert rows[0]["content"] == "first version"
    assert rows[1]["content"] == "second version"


# ── read_knowledge ───────────────────────────────────────────────────────────


def test_read_by_key_prefix(temp_knowledge_db):
    knowledge.write_knowledge("project/svelte-setup", "Svelte 5 setup notes")
    knowledge.write_knowledge("project/api-design", "REST API design guidelines")
    knowledge.write_knowledge("team/onboarding", "Team onboarding checklist")

    results = knowledge.read_knowledge("project/")
    assert len(results) == 2
    keys = {r["key"] for r in results}
    assert keys == {"project/svelte-setup", "project/api-design"}


def test_read_nonexistent_prefix(temp_knowledge_db):
    results = knowledge.read_knowledge("nonexistent/")
    assert results == []


def test_read_returns_newest_first(temp_knowledge_db):
    knowledge.write_knowledge("test/order", "oldest")
    import time
    time.sleep(0.01)
    knowledge.write_knowledge("test/order", "newest")

    results = knowledge.read_knowledge("test/order")
    assert len(results) == 2
    # 最新一筆排最前面（DESC created_at）
    ids = [r["id"] for r in results]
    assert ids[0] != ids[1]  # 兩筆不同 ID
    contents = [r["content"] for r in results]
    assert contents == ["newest", "oldest"], f"expected newest first, got {contents}"


def test_read_respects_limit(temp_knowledge_db):
    for i in range(5):
        knowledge.write_knowledge("test/limit", f"entry {i}")
    results = knowledge.read_knowledge("test/limit", limit=3)
    assert len(results) == 3


# ── get_knowledge ────────────────────────────────────────────────────────────


def test_get_by_id(temp_knowledge_db):
    entry_id = knowledge.write_knowledge("test/get", "get me")
    result = knowledge.get_knowledge(entry_id)
    assert result is not None
    assert result["key"] == "test/get"
    assert result["content"] == "get me"


def test_get_nonexistent_id(temp_knowledge_db):
    result = knowledge.get_knowledge("nonexistent12345678")
    assert result is None


# ── search_knowledge (FTS5) ─────────────────────────────────────────────────


def test_search_finds_matching_content(temp_knowledge_db):
    knowledge.write_knowledge("project/svelte", "Svelte 5 requires Node 18+ and pnpm")
    knowledge.write_knowledge("project/react", "React 19 works with Vite and pnpm")
    knowledge.write_knowledge("team/notes", "Meeting notes for sprint planning")

    results = knowledge.search_knowledge("pnpm")
    assert len(results) >= 2  # 兩筆含 "pnpm"


def test_search_returns_ranked_results(temp_knowledge_db):
    knowledge.write_knowledge("doc/a", "pnpm is a fast package manager for Node.js")
    knowledge.write_knowledge("doc/b", "You can install packages with pnpm")

    results = knowledge.search_knowledge("pnpm")
    assert len(results) >= 2
    # FTS5 rank 欄位存在
    assert "rank" in results[0]


def test_search_no_match(temp_knowledge_db):
    results = knowledge.search_knowledge("zzzznotexists")
    assert results == []


def test_search_respects_limit(temp_knowledge_db):
    for i in range(5):
        knowledge.write_knowledge("test/search", f"searchable content {i}")
    results = knowledge.search_knowledge("searchable", limit=2)
    assert len(results) <= 2


# ── FTS5 sync triggers ──────────────────────────────────────────────────────


def test_fts_stays_in_sync_after_insert(temp_knowledge_db):
    """確認 FTS5 索引在 INSERT 後自動同步。"""
    knowledge.write_knowledge("sync/insert", "unique content for fts sync test")

    conn = sqlite3.connect(temp_knowledge_db)
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM entries_fts WHERE content MATCH 'unique'"
        ).fetchone()
        assert row[0] >= 1
    finally:
        conn.close()


def test_fts_stays_in_sync_after_update(temp_knowledge_db):
    """確認 FTS5 索引在 UPDATE 後自動同步。"""
    entry_id = knowledge.write_knowledge("sync/update", "original content")
    import time
    time.sleep(0.01)

    # Direct SQL update + trigger should handle FTS sync
    conn = sqlite3.connect(temp_knowledge_db)
    try:
        conn.execute(
            "UPDATE entries SET content = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            ("updated content after edit", entry_id),
        )
        conn.commit()
    finally:
        conn.close()

    # FTS should find the UPDATED content, not the old one
    results = knowledge.search_knowledge("updated content after edit")
    assert len(results) >= 1

    # Old content should NOT be found
    old_results = knowledge.search_knowledge("original content")
    assert len(old_results) == 0


# ── metadata round-trip ──────────────────────────────────────────────────────


def test_metadata_round_trip(temp_knowledge_db):
    meta = {"author": "opus", "priority": "high", "tags": ["architecture", "decision"]}
    entry_id = knowledge.write_knowledge("trip/test", "content with metadata", metadata=meta)
    result = knowledge.get_knowledge(entry_id)
    assert result["metadata"] == meta


def test_get_db_path_respects_env(monkeypatch, tmp_path):
    custom = tmp_path / "custom_knowledge.db"
    monkeypatch.setenv("AGENTOS_KNOWLEDGE_DB_PATH", str(custom))
    assert knowledge.get_db_path() == custom


def test_schema_idempotent():
    """多次呼叫 ensure_schema 不應報錯。"""
    assert knowledge.ensure_schema() is True
    assert knowledge.ensure_schema() is True
    assert knowledge.ensure_schema() is True


def test_read_key_with_slashes(temp_knowledge_db):
    """key 含斜線（如 project/svelte/setup）應正常讀取。"""
    knowledge.write_knowledge("project/svelte/setup", "npm install")
    knowledge.write_knowledge("project/svelte/components", "Button.svelte")
    knowledge.write_knowledge("project/react/hooks", "useEffect")

    results = knowledge.read_knowledge("project/svelte/")
    assert len(results) == 2
    keys = {r["key"] for r in results}
    assert keys == {"project/svelte/setup", "project/svelte/components"}

    results = knowledge.read_knowledge("project/svelte/setup")
    assert len(results) == 1
    assert results[0]["content"] == "npm install"


# ── GBrain integration tests ────────────────────────────────────────────────


def test_gbrain_write_silent_when_disabled(monkeypatch, tmp_path):
    """GBrain write should silently skip when disabled."""
    db_path = tmp_path / "knowledge.db"
    monkeypatch.setenv("AGENTOS_KNOWLEDGE_DB_PATH", str(db_path))
    knowledge.ensure_schema()
    # Should not raise even with GBrain disabled
    entry_id = knowledge.write_knowledge("test/gbrain-off", "content when gbrain off")
    assert len(entry_id) == 16


def test_gbrain_read_fallback_when_disabled(monkeypatch, tmp_path):
    """read_knowledge should work normally when GBrain disabled (no fallback)."""
    db_path = tmp_path / "knowledge.db"
    monkeypatch.setenv("AGENTOS_KNOWLEDGE_DB_PATH", str(db_path))
    knowledge.ensure_schema()
    knowledge.write_knowledge("test/existing", "local content")
    results = knowledge.read_knowledge("test/existing")
    assert len(results) == 1
    assert results[0]["content"] == "local content"


def test_gbrain_search_merges_results_when_disabled(monkeypatch, tmp_path):
    """search_knowledge should return local-only results when GBrain disabled."""
    db_path = tmp_path / "knowledge.db"
    monkeypatch.setenv("AGENTOS_KNOWLEDGE_DB_PATH", str(db_path))
    knowledge.ensure_schema()
    knowledge.write_knowledge("test/search", "searchable content for gbrain merge test")
    results = knowledge.search_knowledge("searchable")
    assert len(results) >= 1
    # All results should be local (no source='gbrain')
    for r in results:
        assert r.get("source") != "gbrain"