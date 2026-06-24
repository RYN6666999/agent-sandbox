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

import datetime
import json
import os
import re
import sqlite3
import sys
import threading
import urllib.request
import urllib.error
import uuid
from pathlib import Path
from typing import Any

try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False

_DB_LOCK = threading.Lock()
_SCHEMA_ENSURED_FOR_PATH: str = ""

# ── GBrain integration ──────────────────────────────────────────────────────────

_GBRAIN_DEFAULT_URL = "http://localhost:3457"
_GBRAIN_CONFIG_CACHE: dict[str, Any] | None = None


def _load_gbrain_config() -> dict[str, Any]:
    """Read gbrain settings from data/settings.json. Cached after first read."""
    global _GBRAIN_CONFIG_CACHE
    if _GBRAIN_CONFIG_CACHE is not None:
        return _GBRAIN_CONFIG_CACHE
    settings_path = Path(__file__).parent.parent / "data" / "settings.json"
    try:
        if settings_path.exists():
            raw = settings_path.read_text(encoding="utf-8")
            cfg = json.loads(raw)
            gbrain = cfg.get("gbrain", {})
            if gbrain.get("enabled", False):
                _GBRAIN_CONFIG_CACHE = {
                    "url": gbrain.get("url", _GBRAIN_DEFAULT_URL),
                    "token": gbrain.get("token", ""),
                    "enabled": True,
                }
                return _GBRAIN_CONFIG_CACHE
    except Exception:
        pass
    _GBRAIN_CONFIG_CACHE = {"url": _GBRAIN_DEFAULT_URL, "enabled": False, "token": ""}
    return _GBRAIN_CONFIG_CACHE


def _gbrain_request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: int = 10,
) -> dict[str, Any] | None:
    """Make an HTTP request to GBrain. Returns parsed JSON or None on failure."""
    cfg = _load_gbrain_config()
    if not cfg["enabled"]:
        return None

    url = f"{cfg['url']}{path}"
    try:
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if cfg.get("token"):
            req.add_header("Authorization", f"Bearer {cfg['token']}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as exc:
        print(f"[knowledge] gbrain request failed ({method} {path}): {exc}", file=sys.stderr)
        return None


def _gbrain_write(key: str, content: str, metadata: dict[str, Any] | None = None) -> None:
    """Write a knowledge entry to GBrain as a page via PUT /page?sync=1.

    knowledge.py key → GBrain page slug.
    """
    cfg = _load_gbrain_config()
    if not cfg["enabled"]:
        return

    slug = key
    frontmatter = metadata or {}
    # GBrain only allows specific tag values
    domain = frontmatter.get("domain", "project")
    allowed_tags = {"preference", "fact", "method", "project", "person", "decision"}
    tag = domain if domain in allowed_tags else "project"

    body = {
        "slug": slug,
        "content": content,
        "tags": [tag],
        "source": "agentos",
    }
    if frontmatter:
        body["frontmatter"] = json.dumps(frontmatter, ensure_ascii=False)

    _gbrain_request("PUT", f"/page?sync=1", body=body, timeout=10)


def _gbrain_read(key: str, limit: int = 5) -> list[dict[str, Any]]:
    """Read entries from GBrain by slug prefix. Returns empty list on failure."""
    cfg = _load_gbrain_config()
    if not cfg["enabled"]:
        return []

    import urllib.parse
    params = urllib.parse.urlencode({"slug": key, "limit": limit})
    url = f"{cfg['url']}/page?{params}"

    try:
        req = urllib.request.Request(url, method="GET")
        if cfg.get("token"):
            req.add_header("Authorization", f"Bearer {cfg['token']}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict) and data.get("ok") and data.get("page"):
                page = data["page"]
                return [{
                    "id": f"gbrain-{page.get('slug', key)}",
                    "key": page.get("slug", key),
                    "content": page.get("compiled_truth", ""),
                    "metadata": page.get("frontmatter", {}),
                    "created_at": page.get("created_at", ""),
                    "updated_at": page.get("updated_at", ""),
                    "source": "gbrain",
                }]
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as exc:
        print(f"[knowledge] gbrain read failed for key={key}: {exc}", file=sys.stderr)
    return []


def _gbrain_search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search GBrain via hybrid search. Returns empty list on failure."""
    cfg = _load_gbrain_config()
    if not cfg["enabled"]:
        return []

    import urllib.parse
    params = urllib.parse.urlencode({"q": query, "limit": limit})
    url = f"{cfg['url']}/search?{params}"

    try:
        req = urllib.request.Request(url, method="GET")
        if cfg.get("token"):
            req.add_header("Authorization", f"Bearer {cfg['token']}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = []
            if isinstance(data, dict) and data.get("ok"):
                hits = data.get("results", data.get("hits", []))
                for hit in hits:
                    page = hit.get("page", hit)
                    results.append({
                        "id": f"gbrain-{page.get('slug', '')}",
                        "key": page.get("slug", ""),
                        "content": page.get("compiled_truth", hit.get("snippet", "")),
                        "metadata": page.get("frontmatter", {}),
                        "created_at": page.get("created_at", ""),
                        "updated_at": page.get("updated_at", ""),
                        "rank": hit.get("score", 0),
                        "source": "gbrain",
                    })
            return results
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as exc:
        print(f"[knowledge] gbrain search failed for query={query}: {exc}", file=sys.stderr)
    return []

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

CJK_FTS5_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts_cjk USING fts5(
  content,
  content=entries,
  content_rowid='rowid'
);
"""


def _has_cjk(text: str) -> bool:
    """Check if string contains any CJK character."""
    for ch in text:
        if '\u4e00' <= ch <= '\u9fff':
            return True
    return False


def _tokenize_cjk(text: str) -> str:
    """If text contains CJK characters and jieba is available, tokenize.
    Returns space-separated tokens for FTS5 indexing.
    """
    if not _HAS_JIEBA:
        return text
    # Check if contains CJK characters
    for ch in text:
        if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f' or '\uff00' <= ch <= '\uffef':
            tokens = jieba.lcut(text)
            return ' '.join(tokens)
    return text


def _migrate_schema() -> None:
    """Add new columns to entries table if they don't exist (SQLite ALTER compatibility)."""
    migs = [
        "ALTER TABLE entries ADD COLUMN related_ids TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE entries ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE entries ADD COLUMN last_hit_at TEXT",
        "ALTER TABLE entries ADD COLUMN confidence REAL DEFAULT 1.0",
    ]
    for sql in migs:
        try:
            with _connect() as conn:
                conn.execute(sql)
        except Exception:
            pass  # column already exists (SQLite throws on duplicate ALTER)


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
    """Create tables, FTS virtual table, and sync triggers if they don't exist.
    Uses module-level flag to skip redundant SQLite ops after first call
    (invalidated automatically when AGENTOS_KNOWLEDGE_DB_PATH changes).
    """
    global _SCHEMA_ENSURED_FOR_PATH
    current_path = str(_db_path())
    if _SCHEMA_ENSURED_FOR_PATH == current_path:
        return True
    try:
        with _connect() as conn:
            conn.executescript(ENTRIES_SCHEMA)
            try:
                conn.executescript(FTS5_SCHEMA)
            except sqlite3.OperationalError:
                pass
            try:
                conn.executescript(FTS5_TRIGGERS)
            except sqlite3.OperationalError:
                pass
            try:
                conn.executescript(CJK_FTS5_SCHEMA)
            except sqlite3.OperationalError:
                pass
        _migrate_schema()
        _SCHEMA_ENSURED_FOR_PATH = current_path
        return True
    except Exception as exc:
        print(f"[knowledge] ensure_schema failed: {exc}", file=sys.stderr)
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

    When GBrain is enabled, the entry is also written to GBrain as a page
    via GET /write?action=put_page.
    """
    entry_id = uuid.uuid4().hex[:16]
    meta_json = json.dumps(metadata or {}, ensure_ascii=False)
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'

    ensure_schema()  # ensure schema exists (module-level cache makes subsequent calls free)

    try:
        with _DB_LOCK:
            with _connect() as conn:
                conn.execute(
                    """
                    INSERT INTO entries (id, key, content, metadata, created_at, updated_at, confidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (entry_id, key, content, meta_json, now, now, 1.0),
                )
                # 同步寫入 CJK FTS5 索引（使用 jieba 分詞，best-effort）
                if _HAS_JIEBA:
                    try:
                        tokenized = _tokenize_cjk(content)
                        if tokenized != content:
                            rowid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                            conn.execute(
                                "INSERT INTO entries_fts_cjk(rowid, content) VALUES (?, ?)",
                                (rowid, tokenized),
                            )
                    except Exception:
                        pass  # best-effort, never block write
        # GBrain dual-write: best-effort, non-blocking
        _gbrain_write(key, content, metadata=metadata)
        return entry_id
    except Exception as exc:
        print(f"[knowledge] write_knowledge failed for key={key}: {exc}", file=sys.stderr)
        raise


def update_knowledge(
    entry_id: str,
    content: str | None = None,
    metadata: dict[str, Any] | None = None,
    related_ids: list[str] | None = None,
    confidence: float | None = None,
) -> bool:
    """Update specific fields of an existing entry. Only provided fields change.

    Returns True if update was applied, False if entry not found.
    """
    ensure_schema()
    try:
        updates: list[str] = []
        params: list[Any] = []
        now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'

        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata, ensure_ascii=False))
        if related_ids is not None:
            updates.append("related_ids = ?")
            params.append(",".join(related_ids))
        if confidence is not None:
            updates.append("confidence = ?")
            params.append(max(0.0, min(1.0, confidence)))

        if not updates:
            return False

        updates.append("updated_at = ?")
        params.append(now)
        params.append(entry_id)

        sql = f"UPDATE entries SET {', '.join(updates)} WHERE id = ?"
        with _DB_LOCK:
            with _connect() as conn:
                cur = conn.execute(sql, params)
                return cur.rowcount > 0
    except Exception as exc:
        print(f"[knowledge] update_knowledge failed for id={entry_id}: {exc}", file=sys.stderr)
        return False


def record_access(entry_id: str) -> None:
    """Record a read access: increment access_count and set last_hit_at.

    Best-effort, never raises.
    """
    try:
        now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'
        with _DB_LOCK:
            with _connect() as conn:
                conn.execute(
                    "UPDATE entries SET access_count = access_count + 1, last_hit_at = ? WHERE id = ?",
                    (now, entry_id),
                )
    except Exception:
        pass


def link_entries(source_id: str, target_id: str) -> bool:
    """Create a bidirectional link between two entries.

    Each entry's related_ids field is updated to include the other.
    Returns True if both entries exist and were updated.
    """
    ensure_schema()
    try:
        with _DB_LOCK:
            with _connect() as conn:
                # Get current related_ids for both
                src = conn.execute("SELECT related_ids FROM entries WHERE id=?", (source_id,)).fetchone()
                tgt = conn.execute("SELECT related_ids FROM entries WHERE id=?", (target_id,)).fetchone()
                if not src or not tgt:
                    return False

                src_ids = set(src[0].split(",")) if src[0] else set()
                tgt_ids = set(tgt[0].split(",")) if tgt[0] else set()

                src_ids.add(target_id)
                tgt_ids.add(source_id)

                now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'
                conn.execute("UPDATE entries SET related_ids=?, updated_at=? WHERE id=?",
                             (",".join(sorted(src_ids)), now, source_id))
                conn.execute("UPDATE entries SET related_ids=?, updated_at=? WHERE id=?",
                             (",".join(sorted(tgt_ids)), now, target_id))
                return True
    except Exception as exc:
        print(f"[knowledge] link_entries failed: {exc}", file=sys.stderr)
        return False


def get_knowledge_stats() -> dict[str, Any]:
    """Return brain health summary."""
    ensure_schema()
    try:
        with _connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            linked = conn.execute("SELECT COUNT(*) FROM entries WHERE related_ids != ''").fetchone()[0]
            never_accessed = conn.execute("SELECT COUNT(*) FROM entries WHERE access_count = 0").fetchone()[0]
            avg_conf = conn.execute("SELECT COALESCE(AVG(confidence), 0.0) FROM entries").fetchone()[0]
            return {
                "total_entries": total,
                "linked_entries": linked,
                "never_accessed": never_accessed,
                "avg_confidence": round(avg_conf, 2),
            }
    except Exception as exc:
        return {"error": str(exc)}


def read_knowledge(key: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search knowledge entries by key prefix.

    Returns entries whose key starts with the given prefix, newest first.
    Falls back to GBrain if local results are empty and GBrain is enabled.
    """
    ensure_schema()

    try:
        with _DB_LOCK:
            with _connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, key, content, metadata, created_at, updated_at,
                           related_ids, access_count, last_hit_at, confidence
                    FROM entries
                    WHERE key LIKE ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (f"{key}%", limit),
                ).fetchall()
        local = [_row_to_dict(r) for r in rows]
        for r in local:
            record_access(r["id"])
        if local:
            return local
        # GBrain fallback: try reading from deep memory
        gbrain_results = _gbrain_read(key, limit=limit)
        if gbrain_results:
            return gbrain_results
        return local
    except Exception as exc:
        print(f"[knowledge] read_knowledge failed for key={key}: {exc}", file=sys.stderr)
        raise


def search_knowledge(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Full-text search across knowledge entries using SQLite FTS5.

    Returns entries whose *content* matches the query, ranked by relevance.
    Falls back to LIKE search if FTS5 is unavailable.

    When GBrain is enabled, results are merged with GBrain hybrid search
    results. GBrain results are appended with source='gbrain'.
    """
    ensure_schema()

    try:
        with _DB_LOCK:
            with _connect() as conn:
                # FTS5 fast path — great for ASCII / space-delimited terms.
                rows: list = []
                try:
                    rows = conn.execute(
                        """
                        SELECT e.id, e.key, e.content, e.metadata, e.created_at, e.updated_at,
                               e.related_ids, e.access_count, e.last_hit_at, e.confidence,
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
                    rows = []
                # CJK FTS5 path: only when query contains CJK chars and jieba available
                if not rows and _HAS_JIEBA and _has_cjk(query):
                    try:
                        tokenized_query = ' '.join(jieba.lcut(query))
                        rows = conn.execute(
                            """
                            SELECT e.id, e.key, e.content, e.metadata, e.created_at, e.updated_at,
                                   e.related_ids, e.access_count, e.last_hit_at, e.confidence,
                                   rank
                            FROM entries_fts_cjk
                            JOIN entries e ON e.rowid = entries_fts_cjk.rowid
                            WHERE entries_fts_cjk MATCH ?
                            ORDER BY rank
                            LIMIT ?
                            """,
                            (tokenized_query, limit),
                        ).fetchall()
                    except (sqlite3.OperationalError, sqlite3.DatabaseError):
                        rows = []
                # LIKE fallback: correct for any language, O(n) but fine at personal-brain scale
                if not rows:
                    rows = conn.execute(
                        """
                        SELECT id, key, content, metadata, created_at, updated_at,
                               related_ids, access_count, last_hit_at, confidence,
                               NULL AS rank
                        FROM entries
                        WHERE content LIKE ? OR key LIKE ?
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (f"%{query}%", f"%{query}%", limit),
                    ).fetchall()
        local_results = [_row_to_dict(r) for r in rows]
        for r in local_results:
            record_access(r["id"])

        # GBrain hybrid search: merge with deep memory results
        gbrain_results = _gbrain_search(query, limit=limit)

        if not gbrain_results:
            return local_results

        # Merge: local first (session cache), then GBrain (deep memory)
        # Deduplicate by key (local takes precedence)
        seen_keys = set(r["key"] for r in local_results)
        merged = list(local_results)
        for gr in gbrain_results:
            if gr["key"] not in seen_keys:
                merged.append(gr)
                seen_keys.add(gr["key"])
        return merged[:limit]
    except Exception as exc:
        print(f"[knowledge] search_knowledge failed for query={query}: {exc}", file=sys.stderr)
        raise


def get_knowledge(entry_id: str) -> dict[str, Any] | None:
    """Get a single knowledge entry by its ID, or None if not found."""
    ensure_schema()

    try:
        with _DB_LOCK:
            with _connect() as conn:
                row = conn.execute(
                    """
                    SELECT id, key, content, metadata, created_at, updated_at,
                           related_ids, access_count, last_hit_at, confidence
                    FROM entries
                    WHERE id = ?
                    """,
                    (entry_id,),
                ).fetchone()
        return _row_to_dict(row) if row else None
    except Exception as exc:
        print(f"[knowledge] get_knowledge failed for id={entry_id}: {exc}", file=sys.stderr)
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


def consolidate_experiences(
    experiences: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Batch-consolidate experiences into knowledge base as 'gene/' entries.

    Each experience dict should have:
      - domain (str): coding|architecture|workflow|debugging|model-choice|tooling
      - type (str): bug-fix|decision|insight|pattern|workflow
      - what (str): description of the experience
      - fix (str, optional): what fixed it (for bug-fix type)

    Returns list of {key, entry_id} for each successfully written gene.
    """
    results = []
    for exp in experiences:
        domain = exp.get("domain", "general")
        exp_type = exp.get("type", "insight")
        what = exp.get("what", "")
        fix = exp.get("fix", "")

        # Build content: what + fix if present
        content = what
        if fix:
            content = f"{what}\n\nFix: {fix}"

        # Build a short slug from the first ~50 chars of what
        slug = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]+', '-', what.strip()[:50]).strip('-').lower()[:40]
        if not slug:
            slug = f"experience-{uuid.uuid4().hex[:8]}"
        gene_key = f"gene/{domain}/{slug}"

        metadata = {
            "domain": domain,
            "type": exp_type,
            "date": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d'),
            "tags": exp.get("tags", []),
        }

        entry_id = write_knowledge(gene_key, content, metadata=metadata)
        results.append({"key": gene_key, "entry_id": entry_id})
    return results