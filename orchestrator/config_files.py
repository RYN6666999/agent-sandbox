"""Shared JSON config helpers for base + local override files.

Rules:
- Base files are tracked in git (team defaults).
- Local files are git-ignored (machine/runtime overrides).
- Read path = deep merge(base, local).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent

SETTINGS_BASE_PATH = REPO_ROOT / "data" / "settings.json"
SETTINGS_LOCAL_PATH = REPO_ROOT / "data" / "settings.local.json"

AGENTOS_BASE_PATH = REPO_ROOT / "agentos.json"
AGENTOS_LOCAL_PATH = REPO_ROOT / "agentos.local.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings() -> dict[str, Any]:
    return _deep_merge(_read_json(SETTINGS_BASE_PATH), _read_json(SETTINGS_LOCAL_PATH))


def save_settings_local(data: dict[str, Any]) -> None:
    SETTINGS_LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_LOCAL_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_agentos_config() -> dict[str, Any]:
    return _deep_merge(_read_json(AGENTOS_BASE_PATH), _read_json(AGENTOS_LOCAL_PATH))
