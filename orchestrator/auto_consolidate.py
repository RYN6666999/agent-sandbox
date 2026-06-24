"""Auto-Consolidate (Session D): turn a verification verdict into a brain gene.

After a verification completes, extract one experience from the verdict and
write it to the knowledge base under gene/. This is the self-growth mechanism:
the system remembers what passed and what blocked it, across sessions.

Fires on terminal outcomes only — pass (what worked) and escalate (what blocked,
for the human). "retry" is mid-flight, not yet a lesson, so it is skipped to
keep the brain free of transient noise.

ponytail: thin adapter over consolidate_experiences. No new storage, no new
extraction LLM — run_verification's verdict already carries score/feedback/source.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from contracts.task_spec import TaskSpec
from orchestrator.knowledge import consolidate_experiences

logger = logging.getLogger(__name__)

# Outcomes worth remembering. "retry" is transient — not yet a lesson.
CONSOLIDATE_STATUSES = {"pass", "escalate"}

# ── Pruning 常數 ────────────────────────────────────────────────────────────────
PRUNE_MAX_ENTRIES: int = 1000   # 腦庫最大條目數，超過時 prune 最舊的
PRUNE_MAX_AGE_DAYS: int = 90    # 超過此天數的條目可被 prune

# ── 失敗計數器 ──────────────────────────────────────────────────────────────────
_FAILURE_COUNT: int = 0


def _word_overlap(a: str, b: str) -> float:
    """Jaccard similarity of word sets."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def _detect_domain(task: str) -> str:
    """Detect knowledge domain from task description."""
    if not task:
        return "workflow"
    task_lower = task.lower()
    if any(kw in task_lower for kw in ["修復", "fix", "bug", "錯誤", "測試失敗", "failing", "broken"]):
        return "debugging"
    if any(kw in task_lower for kw in ["設定", "config", "部署", "deploy", "install"]):
        return "architecture"
    if any(kw in task_lower for kw in ["程式", "函式", "class", "implement", "寫一個", "create", "function", "module"]):
        return "coding"
    if any(kw in task_lower for kw in ["測試", "test", "pytest", "unittest"]):
        return "testing"
    return "workflow"


def _is_similar(existing_entry: dict, new_exp: dict) -> bool:
    """Check if a new experience is similar enough to an existing entry to skip.
    
    Two-tier detection:
    1. Key-based: if the new exp generates the same gene key → definitely duplicate
    2. Content-based: text overlap fallback
    """
    existing_content = (existing_entry.get("content") or "").strip()
    new_what = (new_exp.get("what") or "").strip()
    existing_entry_key = (existing_entry.get("key") or "")
    
    if not existing_content or not new_what:
        return False
    
    # Tier 1: Key-based dedup — if the new exp's key already exists, it's a duplicate
    # (The key is built from the what content, so same what → same key)
    if existing_entry_key.startswith("gene/"):
        import re as _re
        new_slug = _re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]+', '-', new_what.strip()[:50]).strip('-').lower()[:40]
        if new_slug and new_slug in existing_entry_key:
            return True
    
    # Tier 2: Content overlap
    existing_task = existing_content.split(":", 1)[-1].strip() if ":" in existing_content else existing_content
    new_task = new_what.split(":", 1)[-1].strip() if ":" in new_what else new_what
    ex_key = existing_task[:60].strip().lower()
    nw_key = new_task[:60].strip().lower()
    if not ex_key or not nw_key:
        return False
    return ex_key == nw_key or _word_overlap(ex_key, nw_key) > 0.4


def verdict_to_experience(spec: TaskSpec, verdict: dict[str, Any]) -> dict[str, Any] | None:
    """Map a run_verification verdict to one consolidate experience.

    Returns None when the outcome is not worth remembering (e.g. "retry")
    or when a similar gene already exists in the brain.
    """
    status = verdict.get("status")
    if status not in CONSOLIDATE_STATUSES:
        return None

    score = verdict.get("score", 0.0)
    source = verdict.get("source") or "unknown"
    task = (spec.why or "").strip()

    if status == "pass":
        exp_type = "pattern"
        extra = ""
        if spec.io_example and spec.io_example.get("input"):
            inp = str(spec.io_example["input"])
            if len(inp) > 60:
                inp = inp[:60] + "..."
            extra = f" | input: {inp}"
        what = f"✅ 通過 (s={score}, {source}) {task[:100]}{extra}"
        fix = ""
        domain = _detect_domain(task)
    else:  # escalate
        exp_type = "bug-fix"
        what = f"❌ 撞線 (s={score}, {source}) {task[:100]}"
        # Better fix: include feedback and fingerprint if available
        fix_parts = []
        fb = verdict.get("feedback") or ""
        if fb and fb.strip():
            fix_parts.append(fb.strip()[:300])
        if spec.io_example and spec.io_example.get("input"):
            inp = str(spec.io_example["input"])
            if len(inp) < 120:
                fix_parts.append(f"target: {inp}")
        fix = " | ".join(fix_parts) if fix_parts else ""
        domain = "workflow"

    exp = {
        "domain": domain,
        "type": exp_type,
        "what": what,
        "fix": fix,
        "tags": [status, source],
    }

    # ── 合併偵測：查腦庫是否有相似基因 ──────────────────────────────────────
    # 先用 gene/ prefix + keywords 搜尋，提高中文命中率
    keywords = task[:50].strip().lower()
    if keywords:
        try:
            from orchestrator import knowledge
            # 搜尋 gene/ 目錄下是否有相似條目
            existing = knowledge.search_knowledge(keywords[:30], limit=5)
            if not existing:
                # 也試 gene prefix
                existing = knowledge.read_knowledge("gene/", limit=20)
            for entry in existing:
                if _is_similar(entry, exp):
                    return None
        except Exception:
            pass  # best-effort, 搜尋失敗仍允許寫入

    return exp


def prune_knowledge(
    max_entries: int | None = None,
    max_age_days: int | None = None,
) -> dict[str, Any]:
    """Prune the knowledge base: age-based + capacity-based.
    
    Strategy:
    1. Remove entries older than max_age_days (keep architecture decisions)
    2. If still over max_entries, remove lowest-confidence, least-accessed, oldest
    
    Returns a dict with pruning stats (or empty dict on failure).
    Never raises.
    """
    if max_entries is None:
        max_entries = PRUNE_MAX_ENTRIES
    if max_age_days is None:
        max_age_days = PRUNE_MAX_AGE_DAYS

    try:
        from orchestrator import knowledge
        stats: dict[str, Any] = {"removed": 0, "age_removed": 0, "capacity_removed": 0, "reason": ""}

        db_path = knowledge.get_db_path()
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(db_path)
        try:
            # Step 1: Age-based — remove entries older than max_age_days
            # (Keep architecture decisions forever — they don't stale)
            if max_age_days > 0:
                cur = conn.execute("""
                    DELETE FROM entries
                    WHERE created_at < datetime('now', '-' || ? || ' days')
                      AND (json_extract(metadata, '$.domain') IS NULL
                           OR json_extract(metadata, '$.domain') != 'architecture')
                """, (max_age_days,))
                stats["age_removed"] = cur.rowcount
                stats["removed"] += cur.rowcount

            # Step 2: Capacity-based — if still over max_entries, remove worst entries
            count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            if count > max_entries:
                excess = count - max_entries
                cur = conn.execute("""
                    DELETE FROM entries
                    WHERE rowid IN (
                        SELECT rowid FROM entries
                        ORDER BY confidence ASC, access_count ASC, created_at ASC
                        LIMIT ?
                    )
                """, (excess,))
                stats["capacity_removed"] = cur.rowcount
                stats["removed"] += cur.rowcount

            conn.commit()
            stats["reason"] = f"age:{stats['age_removed']} capacity:{stats['capacity_removed']}"
            return stats
        finally:
            conn.close()
    except Exception:
        return {"removed": 0, "reason": "prune failed"}


def auto_consolidate(spec: TaskSpec, verdict: dict[str, Any]) -> list[dict[str, Any]]:
    """Best-effort: extract a gene from the verdict and write it to the brain.

    Never raises — a consolidation failure must not break verification. Returns
    the genes written (empty list if skipped or on failure).
    """
    global _FAILURE_COUNT
    exp = verdict_to_experience(spec, verdict)
    if exp is None:
        return []
    try:
        # 先 prune（best-effort，不阻塞主流程）
        prune_knowledge()
        
        return consolidate_experiences([exp])
    except Exception as e:  # best-effort: log, never propagate into verification
        _FAILURE_COUNT += 1
        logger.warning("auto_consolidate failed (verification unaffected): %s", e)
        return []


def get_failure_count() -> int:
    """Return the count of auto-consolidate failures since process start.
    
    Exposes the failure counter for observability. Unlike the old global silent
    swallow, callers can now detect if consolidation is systematically failing.
    """
    return _FAILURE_COUNT


if __name__ == "__main__":
    # ponytail self-check: the routing logic that matters, no framework.
    from contracts.task_spec import TaskSpec as _T

    s = _T(why="x", io_example={"input": "x", "expected_output": ""},
           taste=[], boundaries=[], stop_on_metric="quality", max_rounds=1)
    assert verdict_to_experience(s, {"status": "retry", "score": 4.0}) is None
    p = verdict_to_experience(s, {"status": "pass", "score": 10.0, "source": "pytest"})
    assert p["type"] == "pattern" and p["fix"] == "" and "pass" in p["tags"]
    e = verdict_to_experience(s, {"status": "escalate", "score": 0.0, "feedback": "boom"})
    assert e["type"] == "bug-fix" and e["fix"] == "boom"
    print("auto_consolidate self-check OK")