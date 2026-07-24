"""信任 ratchet — 每任務類一條信任履歷。

ratchet 規則：
  1. 只靠客觀驗證成功爬升（不是自報、不是「以前批准過」）。
  2. 不對稱：難爬易崩 — 做對慢慢加；一次 fail/divergence → 大扣或直接降級。
  3. 最小樣本閘：畢業要過樣本數下限 + 信賴區間，不是連過 N 次就升。
  4. 狀態機：human → sandbox → auto
  5. 🔑 policy (b)（Ryan 拍）：畢業進 auto 不自走 —— 發 needs_ryan_signoff 事件，
     等 Ryan 一次性簽核才真的進 auto。ratchet 自己絕不把任何類升到 auto。
"""
from __future__ import annotations
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, field_validator


# ── 路徑 ────────────────────────────────────────────────────────────────────
_DATA_DIR = Path(
    os.environ.get("AGENTOS_RATCHET_DATA_DIR", str(Path(__file__).parent.parent / "data"))
).expanduser()


def _normalize_namespace(value: str | None) -> str:
    """正規化 namespace，避免非法檔名與路徑逃逸。"""
    ns = (value or "prod").strip()
    if not ns:
        return "prod"
    if not re.fullmatch(r"[A-Za-z0-9_-]+", ns):
        return "prod"
    return ns


_RATCHET_NAMESPACE = _normalize_namespace(os.environ.get("AGENTOS_RATCHET_NAMESPACE", "prod"))

if _RATCHET_NAMESPACE == "prod":
    _RATCHET_PATH = _DATA_DIR / "ratchet.json"
    _EVENTS_PATH = _DATA_DIR / "ratchet_events.log"
else:
    _RATCHET_PATH = _DATA_DIR / f"ratchet.{_RATCHET_NAMESPACE}.json"
    _EVENTS_PATH = _DATA_DIR / f"ratchet_events.{_RATCHET_NAMESPACE}.log"


# ── 常數 ────────────────────────────────────────────────────────────────────
MIN_SAMPLES_FOR_UPGRADE = 10        # 最小樣本閘
CONFIDENCE_INTERVAL_Z = 1.645       # 90% 信賴區間 Z 值
PASS_WEIGHT = 1.0                   # 做對一次加權
FAIL_WEIGHT = 3.0                   # 做錯一次扣權（不對稱：fail > pass）
PASS_THRESHOLD_FOR_SANDBOX = 0.7    # 升 sandbox 的通過率門檻
PASS_THRESHOLD_FOR_AUTO = 0.85      # 升 auto 的通過率門檻
DOWNGRADE_FAIL_RATIO = 0.4          # 失敗率超過此值 → 降級
MAX_CONSECUTIVE_FAILURES = 3        # 連續失敗 N 次 → 降級


class RatchetEntry(BaseModel):
    task_class: str
    level: Literal["human", "sandbox", "auto"] = "human"
    verified_count: int = 0
    failed_count: int = 0
    consecutive_failures: int = 0
    last_verified_at: str | None = None
    needs_signoff: bool = False          # True = pending Ryan approval to enter auto

    @field_validator("task_class")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("task_class must not be empty")
        return v

    @property
    def total(self) -> int:
        return self.verified_count + self.failed_count

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.verified_count / self.total

    @property
    def fail_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.failed_count / self.total

    @property
    def confidence_lower_bound(self) -> float:
        """Wilson 信賴區間下限（90%）。"""
        if self.total == 0:
            return 0.0
        p = self.pass_rate
        n = self.total
        z = CONFIDENCE_INTERVAL_Z
        denominator = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / denominator
        margin = z * math.sqrt((p * (1 - p) / n + z * z / (4 * n * n))) / denominator
        return centre - margin


def _ensure_data_dir() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_ratchet() -> dict[str, RatchetEntry]:
    """從 data/ratchet.json 讀取所有任務類的信任狀態。"""
    _ensure_data_dir()
    if not _RATCHET_PATH.exists():
        return {}
    try:
        raw = json.loads(_RATCHET_PATH.read_text())
        return {k: RatchetEntry(**v) for k, v in raw.items()}
    except (json.JSONDecodeError, ValueError):
        return {}


def save_ratchet(entries: dict[str, RatchetEntry]) -> None:
    """寫回 data/ratchet.json。"""
    _ensure_data_dir()
    raw = {k: v.model_dump() for k, v in entries.items()}
    _RATCHET_PATH.write_text(json.dumps(raw, indent=2, ensure_ascii=False))
    _cleanup_events()


def _append_event(
    entry: RatchetEntry,
    event: str,
    detail: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    """寫入 data/ratchet_events.log（JSONL）。"""
    _ensure_data_dir()
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "namespace": _RATCHET_NAMESPACE,
        "event": event,
        "task_class": entry.task_class,
        "level": entry.level,
        "verified_count": entry.verified_count,
        "failed_count": entry.failed_count,
        "detail": detail,
        "needs_signoff": entry.needs_signoff,
        "pass_rate": round(entry.pass_rate, 6),
        "confidence_lower_bound": round(entry.confidence_lower_bound, 6),
    }
    if metadata:
        record.update(metadata)
    with _EVENTS_PATH.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _cleanup_events() -> None:
    """裁減 events log 至最近 500 行。"""
    if not _EVENTS_PATH.exists():
        return
    lines = _EVENTS_PATH.read_text().strip().split("\n")
    if len(lines) > 500:
        _EVENTS_PATH.write_text("\n".join(lines[-500:]) + "\n")


def update_ratchet(entry: RatchetEntry, passed: bool) -> RatchetEntry:
    """一次驗證成功或失敗後，更新信任履歷並決定是否觸發狀態轉移。

    不對稱升降：一次 fail 扣分 > 一次 pass 加分。
    最小樣本閘：升級需達 MIN_SAMPLES_FOR_UPGRADE 樣本。
    policy(b)：升 auto 不自走，設 needs_signoff=True 並發事件。
    """
    # ── 更新計數 ────────────────────────────────────────────────────────
    if passed:
        entry.verified_count += 1
        entry.consecutive_failures = 0
    else:
        entry.failed_count += 1
        entry.consecutive_failures += 1

    entry.last_verified_at = datetime.now(timezone.utc).isoformat()

    # ── 降級檢查（不對稱：易崩） ────────────────────────────────────────
    if entry.level == "sandbox" and (
        entry.consecutive_failures >= MAX_CONSECUTIVE_FAILURES
        or entry.fail_rate >= DOWNGRADE_FAIL_RATIO
    ):
        old_level = entry.level
        entry.level = "human"
        entry.needs_signoff = False
        _append_event(entry, "downgrade", f"from={old_level} to=human")
        return entry

    if entry.level == "auto" and (
        entry.consecutive_failures >= MAX_CONSECUTIVE_FAILURES
        or entry.fail_rate >= DOWNGRADE_FAIL_RATIO
    ):
        old_level = entry.level
        entry.level = "sandbox"
        entry.needs_signoff = False
        _append_event(entry, "downgrade", f"from={old_level} to=sandbox")
        return entry

    # ── 升級檢查（難爬：最小樣本閘 + 信賴區間） ────────────────────────
    if entry.total < MIN_SAMPLES_FOR_UPGRADE:
        return entry  # 樣本數不足，不升級

    # human → sandbox
    if entry.level == "human" and entry.confidence_lower_bound >= PASS_THRESHOLD_FOR_SANDBOX:
        entry.level = "sandbox"
        _append_event(entry, "upgrade", "from=human to=sandbox")
        return entry

    # sandbox → auto（policy b：不自走）
    if entry.level == "sandbox" and entry.confidence_lower_bound >= PASS_THRESHOLD_FOR_AUTO:
        if not entry.needs_signoff:
            entry.needs_signoff = True
            _append_event(
                entry,
                "needs_ryan_signoff",
                f"verified_count={entry.verified_count} confidence_lower={entry.confidence_lower_bound:.3f}",
                metadata={
                    "signoff_status": "pending",
                    "trigger": "auto_upgrade_threshold_reached",
                    "pass_threshold_for_auto": PASS_THRESHOLD_FOR_AUTO,
                    "min_samples_for_upgrade": MIN_SAMPLES_FOR_UPGRADE,
                },
            )
        # 不升到 auto，只設 needs_signoff

    return entry


def signoff_auto(task_class: str) -> bool:
    """Ryan 一次性簽核：將任務類升到 auto。

    回 True 表示簽核成功，False 表示找不到該任務類或尚未請求簽核。
    """
    entries = load_ratchet()
    entry = entries.get(task_class)
    if entry is None or not entry.needs_signoff:
        return False
    entry.level = "auto"
    entry.needs_signoff = False
    _append_event(
        entry,
        "ryan_signoff",
        "approved to auto",
        metadata={"signoff_status": "approved", "approver": "ryan"},
    )
    save_ratchet(entries)
    return True


def _load_events(limit: int | None = None) -> list[dict[str, Any]]:
    if not _EVENTS_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in _EVENTS_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            rows.append(data)
    if limit is not None and limit > 0:
        return rows[-limit:]
    return rows


def get_signoff_queue() -> list[dict[str, Any]]:
    """回傳待 Ryan 簽核的任務類與最近拒絕原因（若有）。"""
    entries = load_ratchet()
    events = _load_events(limit=500)
    pending: list[dict[str, Any]] = []

    for task_class, entry in sorted(entries.items()):
        if not entry.needs_signoff:
            continue

        last_reject_reason = ""
        last_reject_ts = ""
        for evt in reversed(events):
            if evt.get("task_class") != task_class:
                continue
            if evt.get("event") != "verdict_processed":
                continue
            if evt.get("outcome") != "fail":
                continue
            last_reject_reason = str(evt.get("gate_reason", ""))
            last_reject_ts = str(evt.get("ts", ""))
            break

        pending.append(
            {
                "task_class": task_class,
                "level": entry.level,
                "needs_signoff": entry.needs_signoff,
                "verified_count": entry.verified_count,
                "failed_count": entry.failed_count,
                "pass_rate": round(entry.pass_rate, 6),
                "confidence_lower_bound": round(entry.confidence_lower_bound, 6),
                "last_verified_at": entry.last_verified_at,
                "last_reject_reason": last_reject_reason,
                "last_reject_ts": last_reject_ts,
            }
        )

    return pending