#!/usr/bin/env bash
# diag.sh — Agent Sandbox 診斷報告
# 用法: bash scripts/diag.sh [session_id]
# 輸出貼給 Claude 即可

SESSION_ID="${1:-}"
API="http://localhost:8000"
UI="http://localhost:1420"

echo "===== AGENT SANDBOX DIAG $(date '+%Y-%m-%d %H:%M:%S') ====="
echo ""

# ── 1. 服務狀態 ─────────────────────────────────────────────
echo "### SERVICES"
printf "Backend  : "
HEALTH=$(curl -s --max-time 3 "$API/health" 2>&1)
echo "$HEALTH"

printf "Frontend : "
UI_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$UI/" 2>&1)
echo "HTTP $UI_CODE"
echo ""

# ── 2. Backend process ──────────────────────────────────────
echo "### PROCESSES"
ps aux | grep -E "uvicorn|vite|tauri" | grep -v grep || echo "(none found)"
echo ""

# ── 3. Backend log (最後 50 行) ────────────────────────────
echo "### BACKEND LOG (last 50 lines)"
if [[ -f /tmp/agent-api.log ]]; then
  tail -50 /tmp/agent-api.log
else
  echo "(no log at /tmp/agent-api.log)"
fi
echo ""

# ── 4. UI log ───────────────────────────────────────────────
echo "### UI LOG (last 30 lines)"
if [[ -f /tmp/agent-ui.log ]]; then
  tail -30 /tmp/agent-ui.log
else
  echo "(no log at /tmp/agent-ui.log)"
fi
echo ""

# ── 5. Session 詳情（若有 session_id）──────────────────────
if [[ -n "$SESSION_ID" ]]; then
  echo "### SESSION: $SESSION_ID"
  curl -s --max-time 5 "$API/session/$SESSION_ID" | python3 -m json.tool 2>/dev/null || echo "(fetch failed)"
  echo ""
fi

# ── 6. Cost ─────────────────────────────────────────────────
echo "### COST"
curl -s --max-time 3 "$API/cost" | python3 -m json.tool 2>/dev/null || echo "(fetch failed)"
echo ""

# ── 7. .sdd/ blackboard ─────────────────────────────────────
echo "### BLACKBOARD (.sdd/)"
SDD_DIR="$(dirname "$0")/../.sdd"
if [[ -d "$SDD_DIR" ]]; then
  ls -lt "$SDD_DIR" | head -20
  echo ""
  # 最新一個檔案內容
  LATEST=$(ls -t "$SDD_DIR" | head -1)
  if [[ -n "$LATEST" ]]; then
    echo "--- latest: $LATEST ---"
    cat "$SDD_DIR/$LATEST" | python3 -m json.tool 2>/dev/null | head -40
  fi
else
  echo "(no .sdd/ dir)"
fi
echo ""

# ── 8. Port conflicts ────────────────────────────────────────
echo "### PORT STATUS"
for PORT in 8000 1420; do
  PIDS=$(lsof -ti:$PORT 2>/dev/null)
  if [[ -n "$PIDS" ]]; then
    echo "Port $PORT → PID $PIDS $(ps -p $PIDS -o comm= 2>/dev/null)"
  else
    echo "Port $PORT → free"
  fi
done
echo ""

# ── 9. Python env ────────────────────────────────────────────
echo "### PYTHON ENV"
VENV="$(dirname "$0")/../.venv/bin/python"
if [[ -f "$VENV" ]]; then
  "$VENV" -c "import fastapi, pydantic, litellm, langgraph; print(f'fastapi={fastapi.__version__} pydantic={pydantic.__version__} litellm={litellm.__version__}')" 2>&1
else
  echo "(no .venv found)"
fi
echo ""

echo "===== END DIAG ====="
