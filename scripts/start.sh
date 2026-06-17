#!/usr/bin/env bash
# start.sh — 一鍵起 Agent Sandbox（後端 + 前端）
# 用法: bash scripts/start.sh
# Ctrl+C 同時關兩個

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"

# 清掉殘留 process
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:1420 | xargs kill -9 2>/dev/null
sleep 0.5

echo "▶ backend  → http://localhost:8000"
"$PYTHON" -m uvicorn api.main:app --port 8000 --log-level warning &
BACKEND_PID=$!

echo "▶ frontend → http://localhost:1420"
cd "$ROOT/ui" && npx vite --port 1420 --logLevel warn &
FRONTEND_PID=$!

# 等後端起來
for i in $(seq 1 10); do
  sleep 1
  if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✓ ready"
    break
  fi
done

# Ctrl+C 一起殺
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo ''; echo 'stopped.'" INT TERM
wait $BACKEND_PID $FRONTEND_PID
