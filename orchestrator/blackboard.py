"""Shared blackboard backed by .sdd/ directory. All agents read/write here."""
import json
from datetime import datetime
from pathlib import Path

SDD = Path(__file__).parent.parent / ".sdd"
SDD.mkdir(exist_ok=True)


def write(key: str, data: dict) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    path = SDD / f"{key}_{ts}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return path


def read_latest(key_prefix: str) -> dict | None:
    matches = sorted(SDD.glob(f"{key_prefix}_*.json"))
    if not matches:
        return None
    return json.loads(matches[-1].read_text())


def read_all(key_prefix: str) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(SDD.glob(f"{key_prefix}_*.json"))]
