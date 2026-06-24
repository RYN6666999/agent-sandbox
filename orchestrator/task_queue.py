"""AgentOS 任務佇列 — SQLite 狀態機

狀態機（單向，不可逆回退）：
  pending → running → passed | escalated | dead

語意：
  pending   — 等待被撿（FIFO by created_at）
  running   — 被 runner 取出，執行中（取出時 attempt_count +1）
  passed    — score >= 7.0 達標，任務完成
  escalated — 煞車停：max_rounds / no_progress / max_attempts / 全局預算超限
              → 落 triage 佇列等人工介入
  dead      — 撞線停：score == 0.0（環境錯 / 毒任務）
              → 永不再被 next_pending 撿到，防毒任務空轉燒錢

設計原則：
  - 純 FIFO（created_at ASC），不插隊
  - attempt_count 在 pop（取出）時遞增，不在 push 時設定
  - dead 任務一律過濾，next_pending 保證不回收
  - 審計日誌透過 decision_log 寫入（非強依賴，失敗不中斷主流程）
  - 執行緒安全：所有寫入走同一把 _DB_LOCK

cost_ledger（全局油表真相來源）：
  - 唯一的跨重啟成本累計表，runner 啟動時從這裡重建 spent_usd
  - 時區：localtime（台灣午夜歸零，符合操作者作息）
  - task_queue.cost_usd 是顯示用冗餘值，不作為油表依據
  - cost_known=False 的記錄仍 INSERT（reason='subprocess_unknown'），
    但 cost_usd=0.0，不影響 SUM，僅作審計留存
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts.task_spec import TaskSpec

_DB_LOCK = threading.Lock()
_SCHEMA_ENSURED_FOR_PATH: str = ""

DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "task_queue.db"

# ── 合法狀態集合 ────────────────────────────────────────────────────────────

VALID_STATUSES = frozenset({"pending", "running", "passed", "escalated", "dead"})

# ── schema ──────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_queue (
  task_id       TEXT PRIMARY KEY,
  spec_json     TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','running','passed','escalated','dead')),
  attempt_count INTEGER NOT NULL DEFAULT 0,
  last_score    REAL,
  last_feedback TEXT,
  cost_usd      REAL NOT NULL DEFAULT 0.0,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  notes_json    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_tq_status_created ON task_queue(status, created_at);
"""

# cost_ledger：全局油表真相來源
# - 唯一用於 SUM 的表，task_queue.cost_usd 是顯示冗餘
# - local_date 用 localtime（台灣午夜歸零）
# - cost_known=False 時 cost_usd=0.0，仍留 reason='subprocess_unknown' 作審計
_LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS cost_ledger (
  ledger_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id    TEXT NOT NULL,
  round_n    INTEGER NOT NULL DEFAULT 0,
  cost_usd   REAL NOT NULL DEFAULT 0.0,
  cost_known INTEGER NOT NULL DEFAULT 1,
  reason     TEXT NOT NULL DEFAULT '',
  local_date TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_local_date ON cost_ledger(local_date);
"""


# ── 連線 ────────────────────────────────────────────────────────────────────

def _db_path() -> Path:
    override = os.environ.get("AGENTOS_TASK_QUEUE_DB_PATH", "").strip()
    return Path(override) if override else DEFAULT_DB_PATH


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema() -> None:
    """建立（或確認）資料表結構。冪等，path-aware cache 使後續呼叫近乎免費。"""
    global _SCHEMA_ENSURED_FOR_PATH
    current_path = str(_db_path())
    if _SCHEMA_ENSURED_FOR_PATH == current_path:
        return
    with _DB_LOCK:
        with _connect() as conn:
            conn.executescript(_SCHEMA)
            conn.executescript(_LEDGER_SCHEMA)
    _SCHEMA_ENSURED_FOR_PATH = current_path


# ── 工具 ────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    # 解析 notes_json
    try:
        d["notes"] = json.loads(d.pop("notes_json", "{}"))
    except Exception:
        d["notes"] = {}
    return d


# ── 公開 API ─────────────────────────────────────────────────────────────────

def push(spec: TaskSpec, notes: dict[str, Any] | None = None) -> str:
    """把任務放入佇列，回傳 task_id。

    任務進佇列後 status='pending'、attempt_count=0。
    同一個 spec 每次呼叫都產生新的 task_id（允許重複任務）。
    """
    ensure_schema()
    task_id = str(uuid.uuid4())
    now = _now_iso()
    spec_json = spec.model_dump_json()
    notes_json = json.dumps(notes or {}, ensure_ascii=False)

    with _DB_LOCK:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO task_queue
                  (task_id, spec_json, status, attempt_count,
                   last_score, last_feedback, created_at, updated_at, notes_json)
                VALUES (?, ?, 'pending', 0, NULL, NULL, ?, ?, ?)
                """,
                (task_id, spec_json, now, now, notes_json),
            )
    return task_id


def next_pending() -> dict[str, Any] | None:
    """純 FIFO：取出最早的 pending 任務，將 status 改為 running，attempt_count +1。

    回傳任務 dict（含 spec_json）或 None（佇列空）。
    dead 任務永不被取出（WHERE status='pending' 過濾）。
    """
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM task_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            task_id = row["task_id"]
            now = _now_iso()
            conn.execute(
                """
                UPDATE task_queue
                SET status='running', attempt_count=attempt_count+1, updated_at=?
                WHERE task_id=?
                """,
                (now, task_id),
            )
            # 重新讀取以取得最新的 attempt_count
            updated = conn.execute(
                "SELECT * FROM task_queue WHERE task_id=?", (task_id,)
            ).fetchone()
            return _row_to_dict(updated)


def update_status(
    task_id: str,
    status: str,
    *,
    score: float | None = None,
    feedback: str | None = None,
    notes: dict[str, Any] | None = None,
) -> bool:
    """更新任務狀態。

    status 必須是 VALID_STATUSES 之一。
    若提供 score / feedback / notes，一起寫入。
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status!r}. Must be one of {VALID_STATUSES}")
    ensure_schema()
    now = _now_iso()
    with _DB_LOCK:
        with _connect() as conn:
            if notes is not None:
                notes_json = json.dumps(notes, ensure_ascii=False)
                conn.execute(
                    """
                    UPDATE task_queue
                    SET status=?, last_score=?, last_feedback=?,
                        updated_at=?, notes_json=?
                    WHERE task_id=?
                    """,
                    (status, score, feedback, now, notes_json, task_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE task_queue
                    SET status=?, last_score=?, last_feedback=?, updated_at=?
                    WHERE task_id=?
                    """,
                    (status, score, feedback, now, task_id),
                )
    return True


def get_task(task_id: str) -> dict[str, Any] | None:
    """根據 task_id 取得任務詳情，若不存在回傳 None。"""
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_queue WHERE task_id=?", (task_id,)
            ).fetchone()
    return _row_to_dict(row) if row else None


def list_triage(status: str = "escalated", limit: int = 100) -> list[dict[str, Any]]:
    """列出需要人工介入的任務（預設 status='escalated'）。

    使用情境：隔天一句呼叫就看到整夜 runner 的結果。
    也可傳 status='dead' 查看毒任務。
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status!r}")
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_queue
                WHERE status = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_all(limit: int = 200) -> list[dict[str, Any]]:
    """列出所有任務（除錯用），依 created_at DESC。"""
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_queue ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def queue_depth(status: str = "pending") -> int:
    """回傳指定狀態的任務數量。"""
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM task_queue WHERE status=?", (status,)
            ).fetchone()
    return row[0] if row else 0


# ── cost_ledger 公開 API（全局油表真相來源） ─────────────────────────────────

def ledger_insert(
    task_id: str,
    round_n: int,
    cost_usd: float,
    *,
    cost_known: bool = True,
    reason: str = "",
) -> None:
    """寫入一筆成本流水到 cost_ledger。

    cost_known=False 時 cost_usd 應為 0.0（不影響 SUM），
    reason 填 'subprocess_unknown' 以供審計。
    local_date 用 SQLite localtime，確保台灣午夜歸零。
    """
    ensure_schema()
    now = _now_iso()
    with _DB_LOCK:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO cost_ledger
                  (task_id, round_n, cost_usd, cost_known, reason, local_date, created_at)
                VALUES (?, ?, ?, ?, ?, date('now','localtime'), ?)
                """,
                (task_id, round_n, cost_usd, 1 if cost_known else 0, reason, now),
            )


def ledger_spent_today() -> float:
    """回傳今日（localtime）已記入 cost_ledger 的總成本（USD）。

    runner 啟動時呼叫此函式重建 spent_usd，解決心跳重啟後油表歸零問題。
    只加今日記錄（date('now','localtime')），跨日自動歸零。
    """
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(cost_usd), 0.0)
                FROM cost_ledger
                WHERE local_date = date('now','localtime')
                """,
            ).fetchone()
    return float(row[0]) if row else 0.0


def ledger_update_task_cost(task_id: str, total_cost_usd: float) -> None:
    """更新 task_queue.cost_usd（顯示用冗餘值）。

    僅供 UI / triage 查看單任務花費，不作為油表 SUM 來源。
    """
    ensure_schema()
    now = _now_iso()
    with _DB_LOCK:
        with _connect() as conn:
            conn.execute(
                "UPDATE task_queue SET cost_usd=?, updated_at=? WHERE task_id=?",
                (total_cost_usd, now, task_id),
            )


def find_active_by_fingerprint(fingerprint: str) -> "dict[str, Any] | None":
    """查佇列裡是否已有相同 fingerprint 且「尚未 passed / dead」的任務。

    去重範圍：pending / running / escalated。
    - passed：已修好，允許下次重新產（若又紅代表新的回歸）。
    - dead：環境錯，環境修好後允許重新產（不能讓一次偶發抖動永久封殺此 fingerprint）。
    - escalated：程式碼問題交人，由人手動重試，機器不自動重試（審計可追溯）。

    回傳第一個符合的任務 dict，沒有則回 None。
    SQLite json_extract 查 notes_json 欄位，不另開資料表。
    """
    ensure_schema()
    with _DB_LOCK:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM task_queue
                WHERE json_extract(notes_json, '$.fingerprint') = ?
                  AND status IN ('pending', 'running', 'escalated')
                LIMIT 1
                """,
                (fingerprint,),
            ).fetchone()
    return _row_to_dict(row) if row else None


def count_by_status() -> dict[str, int]:
    """回傳各狀態的任務數量。

    保證五個合法狀態 key 永遠都在（無資料補 0），不因佇列空或某狀態無任務而漏 key。
    """
    ensure_schema()
    # 初始化五個狀態全部為 0，確保 key 不漏
    counts: dict[str, int] = {s: 0 for s in VALID_STATUSES}
    with _DB_LOCK:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM task_queue GROUP BY status"
            ).fetchall()
    for row in rows:
        status, n = row[0], row[1]
        if status in counts:
            counts[status] = n
    return counts
