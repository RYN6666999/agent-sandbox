#!/usr/bin/env bash
# AgentOS heartbeat daemon 控制器 — 讓自修復迴圈實跑一段，自己證明自己。
#
# 用法：
#   scripts/heartbeat-daemon.sh start [interval_sec] [budget_usd]
#   scripts/heartbeat-daemon.sh stop
#   scripts/heartbeat-daemon.sh status
#   scripts/heartbeat-daemon.sh logs
#
# 預設：每 300s 一拍、全局油表上限 $5。
# 便宜模型 = 便宜的拍：tests 全綠時每拍只跑一次 pytest（無 LLM）；
# 只有 test 變紅時 runner 才 call maker（才花錢）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="${AGENTOS_STATE_DIR:-$HOME/.agentos}"
LOG="$STATE_DIR/heartbeat.log"
PIDFILE="$STATE_DIR/heartbeat.pid"
PY="$ROOT/.venv/bin/python"

mkdir -p "$STATE_DIR"

preflight() {
  # 紅線：maker_model 若是 super-engine executor（genspark/web-llm），
  # 無人值守時每次修復都會啟 Brave 瀏覽器 → 不適合 daemon。
  local mm
  mm="$(grep -o '"maker_model"[^,]*' "$ROOT/data/settings.json" | head -1 || true)"
  if echo "$mm" | grep -qiE 'genspark|web-llm'; then
    echo "✗ preflight 擋下：maker_model = $mm"
    echo "  這是 super-engine executor，無人值守跑會每次啟 Brave。"
    echo "  改 data/settings.json 的 maker_model 成 litellm 模型再跑，例如免費的："
    echo '    "maker_model": "openrouter/google/gemma-4-26b-a4b-it:free"'
    echo "  （需要 .env 有 OPENROUTER_API_KEY）"
    exit 1
  fi
  # 提醒：litellm 路徑需要 key，否則 runner 修復會失敗（偵測仍正常）。
  if ! grep -qE '^[A-Z_]*API_KEY=.+' "$ROOT/.env" 2>/dev/null; then
    echo "⚠ .env 沒看到任何非空 API key。inspector 偵測會跑，但 runner 修復會撞線交人。"
  fi
}

cmd="${1:-status}"
case "$cmd" in
  start)
    interval="${2:-300}"
    budget="${3:-5.00}"
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "已在跑 (pid $(cat "$PIDFILE"))。先 stop。"; exit 1
    fi
    preflight
    cd "$ROOT"
    nohup "$PY" -m orchestrator.heartbeat --interval "$interval" --budget "$budget" \
      >> "$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    echo "▶ heartbeat 起跑 pid $(cat "$PIDFILE") | 每 ${interval}s 一拍 | 油表 \$${budget}"
    echo "  log: $LOG"
    echo "  觀察：scripts/heartbeat-daemon.sh logs   /   status"
    ;;
  stop)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      kill "$(cat "$PIDFILE")" && rm -f "$PIDFILE"
      echo "■ 已停。"
    else
      echo "沒在跑。"; rm -f "$PIDFILE"
    fi
    ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "● 跑中 pid $(cat "$PIDFILE")"
    else
      echo "○ 沒在跑"
    fi
    echo "--- 佇列 ---"
    cd "$ROOT" && "$PY" -c "from orchestrator import task_queue; task_queue.ensure_schema(); print(task_queue.count_by_status())" 2>/dev/null || echo "(queue 讀取失敗)"
    echo "--- log 末 8 行 ---"
    tail -n 8 "$LOG" 2>/dev/null || echo "(無 log)"
    ;;
  logs)
    tail -f "$LOG"
    ;;
  *)
    echo "用法: $0 {start [interval] [budget]|stop|status|logs}"; exit 1
    ;;
esac
