"""Triage Auto-Suggest: for escalated tasks, search brain for similar fixes.

Reduces human triage time by surfacing relevant past experiences from the
knowledge base (gene/ entries).
"""
from __future__ import annotations

import json
import re
from typing import Any


def _extract_keywords(task: dict) -> str:
    """Extract search keywords from an escalated task.
    
    Sources (in priority order):
    1. fingerprint from notes (for inspector-A tasks)
    2. spec.why (human-readable task description)
    3. last_feedback (error/failure details)
    """
    parts = []

    notes = task.get("notes") or {}
    fingerprint = notes.get("fingerprint", "")
    if fingerprint:
        # Parse "tests/test_foo.py::test_bar" → "foo bar"
        clean = fingerprint.replace("tests/", "").replace(".py", "").replace("::", " ")
        clean = re.sub(r"^test_", "", clean)
        clean = re.sub(r"\s+test_", " ", clean)
        parts.append(clean.strip())

    spec_json = task.get("spec_json", "{}")
    try:
        spec = json.loads(spec_json) if isinstance(spec_json, str) else spec_json
        why = (spec.get("why") or "").strip()
        if why:
            # Remove "修復失敗測試：" prefix if present
            why_clean = re.sub(r"^修復失敗測試[：:]", "", why).strip()
            parts.append(why_clean[:100])
    except (json.JSONDecodeError, AttributeError):
        pass

    feedback = (task.get("last_feedback") or "").strip()
    if feedback:
        parts.append(feedback[:100])

    return " ".join(p for p in parts if p) or task.get("task_id", "")


def suggest_fix(task: dict, max_results: int = 3) -> dict[str, Any] | None:
    """Search brain for similar fix experiences.
    
    Args:
        task: task dict from task_queue.get_task()
        max_results: max brain entries to return
    
    Returns:
        {
            "task_id": str,
            "query": str,
            "suggestions": [
                {
                    "key": "gene/workflow/login-timeout",
                    "content": "...",
                    "similarity": 0.85,
                    "timestamp": "..."
                }
            ]
        }
        or None if no suggestions found.
    """
    query = _extract_keywords(task)
    if not query:
        return None

    try:
        from orchestrator import knowledge

        results = knowledge.search_knowledge(query, limit=max_results)
    except Exception:
        return None

    if not results:
        return None

    suggestions = []
    for r in results:
        key = r.get("key", "")
        content = (r.get("content") or "")[:200]
        created = r.get("created_at", "")

        # Compute simple similarity: keyword overlap between query and content
        query_words = set(query.lower().split())
        content_words = set(content.lower().split())
        overlap = len(query_words & content_words)
        total = len(query_words | content_words) or 1
        similarity = round(overlap / total, 2) if total > 0 else 0.0

        # Track brain access so confidence decays for unused entries
        try:
            knowledge.record_access(r.get("id", ""))
        except Exception:
            pass

        suggestions.append({
            "key": key,
            "content": content,
            "similarity": similarity,
            "timestamp": created,
        })

    # Sort by similarity descending
    suggestions.sort(key=lambda s: s["similarity"], reverse=True)

    return {
        "task_id": task.get("task_id", ""),
        "query": query,
        "suggestions": suggestions,
    }