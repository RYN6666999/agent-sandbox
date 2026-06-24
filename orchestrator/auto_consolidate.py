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


def _is_similar(existing_entry: dict, new_exp: dict) -> bool:
    """Check if an existing brain entry and a new experience are similar enough
    to skip writing a duplicate gene.
    
    Simple heuristic: compare the 'what' field (first 80 chars) of the new exp
    against the existing entry's content. If they share significant overlap
    (same task type, similar description), treat as duplicate.
    """
    existing_content = (existing_entry.get("content") or "").strip()
    new_what = (new_exp.get("what") or "").strip()
    
    if not existing_content or not new_what:
        return False
    
    # Extract task description part (after the colon)
    existing_task = existing_content.split(":", 1)[-1].strip() if ":" in existing_content else existing_content
    new_task = new_what.split(":", 1)[-1].strip() if ":" in new_what else new_what
    
    # If same task keyword (first 40 chars of task description), treat as similar
    existing_key = existing_task[:40].strip().lower()
    new_key = new_task[:40].strip().lower()
    
    if not existing_key or not new_key:
        return False
    
    return existing_key == new_key or _word_overlap(existing_key, new_key) > 0.6


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
        what = f"任務通過驗收 (score {score}, via {source}): {task}"
        fix = ""
    else:  # escalate
        exp_type = "bug-fix"
        what = f"任務撞線需人介入 (score {score}, via {source}): {task}"
        fix = verdict.get("feedback") or ""

    exp = {
        "domain": "workflow",
        "type": exp_type,
        "what": what,
        "fix": fix,
        "tags": [status, source],
    }

    # ── 合併偵測：查腦庫是否有相似基因 ──────────────────────────────────────
    # 從 task 中萃取關鍵詞用於搜尋
    keywords = task[:50].strip().lower()
    if keywords:
        try:
            from orchestrator import knowledge
            existing = knowledge.search_knowledge(
                keywords[:30], limit=3
            )
            for entry in existing:
                if _is_similar(entry, exp):
                    # 相似內容已存在，不回傳（auto_consolidate 就不會寫入）
                    return None
        except Exception:
            pass  # best-effort, 搜尋失敗仍允許寫入

    return exp


def prune_knowledge(
    max_entries: int | None = None,
    max_age_days: int | None = None,
) -> dict[str, Any]:
    """Prune the knowledge base: remove oldest entries if over capacity.
    
    Returns a dict with pruning stats (or empty dict on failure).
    Never raises.
    """
    # Read module constants at call time so monkeypatches in tests take effect
    if max_entries is None:
        max_entries = PRUNE_MAX_ENTRIES
    if max_age_days is None:
        max_age_days = PRUNE_MAX_AGE_DAYS

    try:
        from orchestrator import knowledge
        from datetime import datetime, timezone
        
        stats = {"removed": 0, "reason": ""}
        
        # 取得總條目數
        db_path = knowledge.get_db_path()
        import sqlite3
        conn = sqlite3.connect(db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            if count <= max_entries:
                stats["reason"] = f"within limit ({count}/{max_entries})"
                return stats
            
            excess = count - max_entries
            # 刪除最舊的 excess 條目
            conn.execute("""
                DELETE FROM entries
                WHERE rowid IN (
                    SELECT rowid FROM entries
                    ORDER BY created_at ASC
                    LIMIT ?
                )
            """, (excess,))
            conn.commit()
            stats["removed"] = conn.total_changes
            stats["reason"] = f"pruned {excess} oldest entries ({count}→{count-excess})"
        finally:
            conn.close()
        
        return stats
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