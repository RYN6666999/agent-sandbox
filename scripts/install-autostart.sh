#!/usr/bin/env bash
# Level 2「預設執行」— 裝一個 macOS LaunchAgent，讓 AgentOS server 登入就自動起、
# 永遠在（崩了自動重啟）。裝完任何 agent 直接用 :8000，零喚醒。
#
#   scripts/install-autostart.sh            # 安裝 + 載入
#   scripts/install-autostart.sh status     # 看狀態
#   scripts/install-autostart.sh --uninstall # 移除
#
# plist 含本機絕對路徑，由本腳本就地生成（不進 repo）。
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.agentos.server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/.agentos/server.log"

_alive() { curl -s -m 2 http://localhost:8000/health 2>/dev/null | grep -q '"ok"'; }

uninstall() {
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "■ 已移除自動啟動（$LABEL）。server 本次仍在跑的話：scripts/agentos.sh down"
}

case "${1:-install}" in
    --uninstall|uninstall) uninstall; exit 0 ;;
    status)
        if launchctl list 2>/dev/null | grep -q "$LABEL"; then
            echo "● 已安裝 LaunchAgent（$LABEL）"; _alive && echo "  server 活著" || echo "  server 沒回應"
        else
            echo "○ 未安裝"
        fi
        exit 0 ;;
esac

[ -x "$REPO/.venv/bin/uvicorn" ] || { echo "✗ 找不到 $REPO/.venv/bin/uvicorn，先跑 uv sync" >&2; exit 1; }
mkdir -p "$HOME/.agentos" "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$REPO/.venv/bin/uvicorn</string>
    <string>api.main:app</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>8000</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
PLIST

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "▶ 已裝 LaunchAgent，等 server 起來…"
for _ in $(seq 1 30); do sleep 0.5; _alive && break; done
if _alive; then
    echo "● AgentOS 現在登入就自動起、永遠在（崩了自動重啟）。"
    echo "  WorkingDirectory=$REPO（.env 會被 maker load_dotenv 讀到）"
    echo "  log: $LOG"
    echo "  移除：scripts/install-autostart.sh --uninstall"
else
    echo "⚠ 尚未起，看 $LOG" >&2; exit 1
fi
