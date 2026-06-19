"""SQLite-backed knowledge base (腦庫) for cross-session persistent memory.

Provides unified read/write interface (`write_knowledge` / `read_knowledge`)
with full-text search (FTS5). This is a parallel storage layer to the audit
log (decision_log) — one stores *what happened*, the other stores *what
should be known*.

Usage:
    from orchestrator.knowledge import write_knowledge, read_knowledge

    entry_id = write_knowledge("project/svelte-setup",
                               "Need Node 18+ and pnpm for Svelte 5",
                               metadata={"author": "opus", "priority": "high"})

    results = read_knowledge("project/svelte")
    results = search_knowledge("svelte setup")
    entry   = get_knowledge(entry_id)
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

_DB_LOCK = threading.Lock()

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "knowledge.db"

ENTRIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
  id TEXT PRIMARY KEY,
  key TEXT NOT NULL,
  content TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_entries_key ON entries(key);
CREATE INDEX IF NOT EXISTS idx_entries_created_at ON entries(created_at);
"""

FTS5_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
  content,
  content=entries,
  content_rowid='rowid'
);
"""

FTS5_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
  INSERT INTO entries_fts(rowid, content) VALUES (new.rowid, new.content);
END;
CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
  INSERT INTO entries_fts(entries_fts, rowid, content) VALUES('delete', old.rowid, old.content);
END;
CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
  INSERT INTO entries_fts(entries_fts, rowid, content) VALUES('delete', old.rowid, old.content);
  INSERT INTO entries_fts(rowid, content) VALUES (new.rowid, new.content);
END;
"""


def _db_path() -> Path:
    override = os.environ.get("AGENTOS_KNOWLEDGE_DB_PATH", "").strip()
    return Path(override) if override else DEFAULT_DB_PATH


def get_db_path() -> Path:
    return _db_path()


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema() -> bool:
    """Create tables, FTS virtual table, and sync triggers if they don't exist."""
    try:
        with _DB_LOCK:
            with _connect() as conn:
                conn.executescript(ENTRIES_SCHEMA)
                # FTS5 virtual table + triggers (wrapped in try/ignore for re-run safety)
                try:
                    conn.executescript(FTS5_SCHEMA)
                except sqlite3.OperationalError:
                    pass  # already exists
                try:
                    conn.executescript(FTS5_TRIGGERS)
                except sqlite3.OperationalError:
                    pass  # already exists
        return True
    except Exception as exc:
        print(f"[knowledge] ensure_schema failed: {exc}", file=__import__('sys').stderr)
        return False


def write_knowledge(
    key: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Write a knowledge entry. Returns the entry_id (UUID).

    If an entry with the same *key* already exists, it is **appended** as a
    new row — keys are not unique. This preserves a history of updates for
    the same topic.
    """
    entry_id = uuid.uuid4().hex[:16]
    meta_json = json.dumps(metadata or {}, ensure_ascii=False)
    now = __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'

    try:
        with _DB_LOCK:
            with _connect() as conn:
                conn.executescript(ENTRIES_SCHEMA)
                conn.execute(
                    """
                    INSERT INTO entries (id, key, content, metadata, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (entry_id, key, content, meta_json, now, now),
                )
        return entry_id
    except Exception as exc:
        print(f"[knowledge] write_knowledge failed for key={key}: {exc}", file=__import__('sys').stderr)
        raise


def read_knowledge(key: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search knowledge entries by key prefix.

    Returns entries whose key starts with the given prefix, newest first.
    """
    try:
        with _DB_LOCK:
            with _connect() as conn:
                conn.executescript(ENTRIES_SCHEMA)
                rows = conn.execute(
                    """
                    SELECT id, key, content, metadata, created_at, updated_at
                    FROM entries
                    WHERE key LIKE ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (f"{key}%", limit),
                ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        print(f"[knowledge] read_knowledge failed for key={key}: {exc}", file=__import__('sys').stderr)
        raise


def search_knowledge(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Full-text search across knowledge entries using SQLite FTS5.

    Returns entries whose *content* matches the query, ranked by relevance.
    Falls back to LIKE search if FTS5 is unavailable.
    """
    try:
        with _DB_LOCK:
            with _connect() as conn:
                # Try FTS5 search first
                try:
                    rows = conn.execute(
                        """
                        SELECT e.id, e.key, e.content, e.metadata, e.created_at, e.updated_at,
                               rank
                        FROM entries_fts
                        JOIN entries e ON e.rowid = entries_fts.rowid
                        WHERE entries_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                        """,
                        (query, limit),
                    ).fetchall()
                except (sqlite3.OperationalError, sqlite3.DatabaseError):
                    # FTS5 not available or not built — fallback to LIKE
                    rows = conn.execute(
                        """
                        SELECT id, key, content, metadata, created_at, updated_at,
                               NULL AS rank
                        FROM entries
                        WHERE content LIKE ? OR key LIKE ?
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (f"%{query}%", f"%{query}%", limit),
                    ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as exc:
        print(f"[knowledge] search_knowledge failed for query={query}: {exc}", file=__import__('sys').stderr)
        raise


def get_knowledge(entry_id: str) -> dict[str, Any] | None:
    """Get a single knowledge entry by its ID, or None if not found."""
    try:
        with _DB_LOCK:
            with _connect() as conn:
                conn.executescript(ENTRIES_SCHEMA)
                row = conn.execute(
                    """
                    SELECT id, key, content, metadata, created_at, updated_at
                    FROM entries
                    WHERE id = ?
                    """,
                    (entry_id,),
                ).fetchone()
        return _row_to_dict(row) if row else None
    except Exception as exc:
        print(f"[knowledge] get_knowledge failed for id={entry_id}: {exc}", file=__import__('sys').stderr)
        raise


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    # Parse JSON metadata back to dict
    if isinstance(d.get("metadata"), str):
        try:
            d["metadata"] = json.loads(d["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d