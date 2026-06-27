"""
Dangerous-command gate — pure rules, 0 LLM calls.

Principle: block "irreversible, wide-scope destruction of the execution
environment". Do NOT block business-logic deletions that run inside a sandbox
(e.g. "刪除重複資料", "delete duplicate rows").

Tune the lists below to widen or narrow coverage.
"""
import re

# ── tuneable constants ────────────────────────────────────────────────────────

# Literal substring matches (case-insensitive).
# Keep entries specific enough to avoid business-logic false positives.
_LITERAL_TRIGGERS: list[str] = [
    "rm -rf",
    "rm -r",
    "push --force",
    "push -f",
    "drop table",
    "truncate table",
    "truncate ",          # "TRUNCATE users" etc.
    # "delete from" handled by regex below (needs WHERE check)
    "清空資料庫",
    "格式化硬碟",
    "格式化磁碟",
    "> /dev/",            # redirect-to-device overwrite
    # System-level destructive commands
    "shutdown",
    "reboot",
    "poweroff",
    "init 0",
    "halt",
]

# Regex patterns (case-insensitive, compiled once).
# Use for patterns that need word boundaries or variable spacing.
_PATTERN_TRIGGERS: list[re.Pattern] = [
    re.compile(r'\brm\s+-[rR][fF]\b'),          # rm -rf / rm -fr
    re.compile(r'\brm\s+-[fF][rR]\b'),
    re.compile(r'git\s+push\s+.*--force'),
    re.compile(r'git\s+push\s+.*-f\b'),
    re.compile(r'DROP\s+TABLE', re.IGNORECASE),
    re.compile(r'TRUNCATE\s+\w', re.IGNORECASE),
    # DELETE FROM <table> with no WHERE clause — whole-table wipe
    re.compile(r'DELETE\s+FROM\s+\w+\s*(?:;|$)(?!\s*WHERE)', re.IGNORECASE),
]


# ── restricted paths ──────────────────────────────────────────────────────────

def _load_restricted_paths() -> list[str]:
    """Read restricted_paths from settings.json."""
    try:
        import json as _json
        from pathlib import Path as _Path
        sp = _Path(__file__).resolve().parent.parent / "data" / "settings.json"
        return _json.loads(sp.read_text()).get("restricted_paths", [])
    except Exception:
        return []


_RESTRICTED_PATHS_CACHE: list[str] = []


def touches_restricted_path(text: str) -> tuple[bool, list[str]]:
    """Check whether a command string references any restricted directory.

    Returns:
        (False, [])           — no restricted path referenced
        (True,  [path, …])   — matched restricted paths
    """
    global _RESTRICTED_PATHS_CACHE
    if not _RESTRICTED_PATHS_CACHE:
        _RESTRICTED_PATHS_CACHE = _load_restricted_paths()
    if not _RESTRICTED_PATHS_CACHE:
        return False, []
    lo = text.lower()
    matched: list[str] = []
    for rp in _RESTRICTED_PATHS_CACHE:
        if rp.lower() in lo:
            matched.append(rp)
    return bool(matched), matched


# ── public API ────────────────────────────────────────────────────────────────

def is_dangerous(text: str) -> tuple[bool, list[str]]:
    """
    Pure rules, 0 LLM calls.

    Returns:
        (False, [])           — safe to proceed
        (True, [trigger, …])  — dangerous; list contains what matched
    """
    lo = text.lower()
    matched: list[str] = []

    for lit in _LITERAL_TRIGGERS:
        if lit.lower() in lo:
            matched.append(lit.strip())

    for pat in _PATTERN_TRIGGERS:
        m = pat.search(text)
        if m:
            token = m.group(0).strip()
            if token not in matched:
                matched.append(token)

    return bool(matched), matched


def check_command(text: str) -> tuple[bool, list[str]]:
    """Combined gate check: dangerous command OR restricted path.

    Returns:
        (False, [])           — safe
        (True,  [reason, …])  — blocked; reasons explain what matched
    """
    danger, danger_reasons = is_dangerous(text)
    restricted, restricted_reasons = touches_restricted_path(text)
    reasons = danger_reasons + restricted_reasons
    return bool(reasons), reasons
