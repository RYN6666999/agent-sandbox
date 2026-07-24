#!/usr/bin/env python3
"""監控 Scream phase + Aris channel，合併寫入 ~/.scream-code/timeline.jsonl。

雙來源：
  /tmp/scream-phase.json      ← Scream agent 寫入（我，tool call 前/後）
  /tmp/aris-scream-channel.jsonl ← Aris ToolExecutor 寫入（type: tool_execution）

啟動：
    python3 ~/agent-sandbox/scripts/scream-phase-logger.py &
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

PHASE = Path("/tmp/scream-phase.json")
CHANNEL = Path("/tmp/aris-scream-channel.jsonl")
CURSOR = Path("/tmp/aris-scream-channel-cursor.json")
DB = Path.home() / ".scream-code" / "timeline.jsonl"
PIDFILE = Path("/tmp/scream-phase-logger.pid")
MAX_LINES = 500
POLL = 0.5
SEEN_TS: set[float] = set()  # Scream phase 去重（by ts）


def _read_cursor() -> int:
    try:
        return json.loads(CURSOR.read_text("utf-8")).get("offset", 0)
    except Exception:
        return 0


def _write_cursor(offset: int):
    CURSOR.write_text(json.dumps({"offset": offset}), "utf-8")


def _append(ev: dict):
    ts = ev.get("ts", 0)
    if ts in SEEN_TS:
        return
    SEEN_TS.add(ts)
    DB.parent.mkdir(parents=True, exist_ok=True)
    with DB.open("a") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def truncate():
    if not DB.exists() or DB.stat().st_size < 50000:
        return
    lines = DB.read_text("utf-8").strip().split("\n")
    if len(lines) > MAX_LINES:
        DB.write_text("\n".join(lines[-MAX_LINES:]) + "\n", "utf-8")


def poll_scream_phase():
    """讀取 Scream agent 寫入的 phase 事件（JSONL, 我寫的）。"""
    if not PHASE.exists():
        return
    raw = PHASE.read_text("utf-8").strip()
    if not raw:
        return
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        _append(ev)


def poll_aris_channel():
    """讀取 Aris channel 中的 tool_execution 事件（JSONL, 他寫的）。"""
    if not CHANNEL.exists():
        return
    offset = _read_cursor()
    try:
        raw = CHANNEL.read_text("utf-8")
    except Exception:
        return
    if len(raw) <= offset:
        return
    new_data = raw[offset:]
    _write_cursor(len(raw))

    for line in new_data.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "tool_execution":
            # 正規化為統一格式
            normalized = {
                "tool": ev.get("tool", ""),
                "status": ev.get("status", ""),
                "ts": ev.get("ts", 0),
                "icon": ev.get("icon", "⚙"),
                "description": ev.get("description", ""),
                "elapsed": ev.get("elapsed", 0),
                "_source": "aris",
            }
            _append(normalized)


def write_pid():
    PIDFILE.write_text(str(os.getpid()) + "\n")


def main():
    if PIDFILE.exists():
        try:
            old = int(PIDFILE.read_text().strip())
            os.kill(old, 0)
            print(f"[phase-logger] 已在執行 (PID {old})，跳過")
            return
        except (OSError, ValueError):
            pass
    write_pid()
    print(f"[phase-logger] 啟動 (PID {os.getpid()}) | 監聽 Scream phase + Aris channel")
    try:
        while True:
            poll_scream_phase()
            poll_aris_channel()
            truncate()
            time.sleep(POLL)
    except KeyboardInterrupt:
        PIDFILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()