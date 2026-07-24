#!/usr/bin/env python3
"""讀取 timeline.jsonl → 格式化時間軸 / 目前狀態 / 統計。

支援雙來源：
  Scream phase: {tool, status, ts}
  Aris tool_execution: {tool, status, ts, icon, description, elapsed, _source: "aris"}

用法：
    ~/agent-sandbox/scripts/scream-timeline.py           # 完整時間軸
    ~/agent-sandbox/scripts/scream-timeline.py --status   # 目前工具狀態
    ~/agent-sandbox/scripts/scream-timeline.py --json     # 原始 JSON
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

DB = Path.home() / ".scream-code" / "timeline.jsonl"

ICON = {
    "start": "▶",
    "running": "🔄",
    "done": "✅",
    "fail": "❌",
    "thinking": "💭",
    "composing": "✍",
    "idle": "○",
}

STATUS_LABEL = {
    "start": "開始",
    "running": "執行中",
    "done": "完成",
    "fail": "失敗",
    "thinking": "思考",
    "composing": "回應",
    "idle": "閒置",
}


def read() -> list[dict]:
    if not DB.exists():
        return []
    out: list[dict] = []
    bad = 0
    for line in DB.read_text("utf-8").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    if bad:
        print(f"(略過 {bad} 行損毀資料)", file=sys.stderr)
    return out


def _tool_name(ev: dict) -> str:
    """從事件中取出工具名稱，含來源標記。"""
    name = ev.get("tool", "") or ""
    source = ev.get("_source", "")
    if source == "aris" and name:
        return f"{name} [Aris]"
    return name


def format_timeline(events: list[dict]):
    print(f"┌─ AI 時間軸{'─'*40}")
    for ev in events[-40:]:
        s = ev.get("status", "")
        tool = _tool_name(ev)
        if not tool:
            tool = STATUS_LABEL.get(s, s)
        ts_ms = ev.get("ts", 0)
        ts_sec = ts_ms / 1000 if ts_ms > 1e12 else ts_ms  # 支援 ms 和 s
        dt = time.strftime("%H:%M:%S", time.localtime(ts_sec))
        icon = ICON.get(s, "○")
        desc = ev.get("description", "")
        elapsed = ""
        if s in ("done", "fail") and ev.get("elapsed"):
            elapsed = f" ({ev['elapsed']:.1f}s)"
        line = f"│ {icon} {dt}  {tool:<16s} {s}{elapsed}"
        if desc:
            line += f"  {desc[:40]}"
        print(line)
    print(f"└─{'─'*55}")
    stats(events)


def stats(events: list[dict]):
    cnt: Counter[str] = Counter()
    dur: Counter[str] = Counter()
    stack: dict[str, float] = {}

    for ev in events:
        tool = _tool_name(ev) or "?"
        status = ev.get("status", "")
        ts = ev.get("ts", 0)
        if ts > 1e12:
            ts = ts / 1000
        if status == "start":
            stack[tool] = ts
            cnt[tool] += 1
        elif status in ("done", "fail"):
            start = stack.pop(tool, None)
            if start:
                dur[tool] += ts - start
                el = ev.get("elapsed")
                if el and el > (ts - start):
                    dur[tool] += el - (ts - start)  # 用 Aris 提供的 elapsed
        elif status in ("thinking", "composing"):
            cnt["_inner"] += 1

    print(f"\n頻率與累計時間（前 10）：")
    for tool, c in cnt.most_common(10):
        if tool == "_inner":
            continue
        d = dur.get(tool, 0)
        avg = d / c if c else 0
        print(f"  {tool:<20s} × {c:>3d}  總 {d:.1f}s  均 {avg:.2f}s")

    # 來源統計
    aris_cnt = sum(1 for e in events if e.get("_source") == "aris")
    scream_cnt = len(events) - aris_cnt
    print(f"\n來源：Aris {aris_cnt} 事件 | Scream {scream_cnt} 事件 | 總計 {len(events)}")


def status() -> str | None:
    """回傳最近一次進行中的工具名稱+時間。"""
    events = read()
    if not events:
        return None
    for ev in reversed(events):
        if ev.get("status") == "start" and ev.get("tool"):
            elapsed = time.time() - (ev["ts"] / 1000 if ev["ts"] > 1e12 else ev["ts"])
            tool = _tool_name(ev)
            if elapsed < 60:
                return f"{tool} {elapsed:.0f}s"
            else:
                return f"{tool} {elapsed/60:.0f}m"
        if ev.get("status") in ("done", "fail"):
            return None
    return None


def main():
    ap = argparse.ArgumentParser(description="Scream Code 工作階段時間軸")
    ap.add_argument("--status", action="store_true", help="輸出目前進行中的工具狀態")
    ap.add_argument("--json", action="store_true", help="輸出原始 JSON")
    args = ap.parse_args()
    events = read()

    if args.json:
        print(json.dumps(events, ensure_ascii=False, indent=2))
        return
    if args.status:
        s = status()
        sys.stdout.write(s or "idle")
        return
    if not events:
        print("尚無時間軸資料。請先執行一些工具呼叫。")
        return
    format_timeline(events)


if __name__ == "__main__":
    main()