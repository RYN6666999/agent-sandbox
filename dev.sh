#!/bin/bash
# 一條指令啟動 AgentOS 開發環境
# 後端 uvicorn (port 8000) + 前端 vite dev (port 5173)
# Ctrl+C 同時關掉兩個

ROOT="$(cd "$(dirname "$0")" && pwd)"

# 殺掉舊的殘留 process
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:5173 | xargs kill -9 2>/dev/null

echo "▶ 後端啟動 http://localhost:8000"
cd "$ROOT"
.venv/bin/uvicorn api.main:app --reload --port 8000 &
BACKEND_PID=$!

echo "▶ 前端啟動 http://localhost:5173"
cd "$ROOT/ui"
npm run dev &
FRONTEND_PID=$!

# Ctrl+C 同時停兩個
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM

wait
