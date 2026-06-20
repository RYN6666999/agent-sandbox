#!/bin/bash
# =============================================================================
# AgentOS 雙管道傳遞測試 — GenSpark(Opus) 送達驗證
#
# 測試兩個管道：
#   Pipeline A: super-engine-warm daemon（HTTP POST localhost:3456）
#   Pipeline B: super-engine one-shot CLI（node ask.ts）
#
# 評估指標：
#   1. 基礎設施是否就緒
#   2. 提示詞能否成功送達
#   3. 回應時間（秒）
#   4. 回應是否為有效 JSON
#   5. 內容品質（有內容 vs 空/錯誤）
#
# 使用方式：
#   bash scripts/test-opus-pipelines.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROMPT_FILE="$SCRIPT_DIR/.scream-code/prompt-to-opus-review.md"
DAEMON_PORT=3456
TIMEOUT=120  # GenSpark 較慢，給 120s

# 顏色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

PASS=0
FAIL=0
RESULTS=()

log()    { echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $*"; }
pass()   { echo -e "  ${GREEN}✅ $*${NC}"; PASS=$((PASS + 1)); }
fail()   { echo -e "  ${RED}❌ $*${NC}"; FAIL=$((FAIL + 1)); }
warn()   { echo -e "  ${YELLOW}⚠️  $*${NC}"; }
header() { echo -e "\n${YELLOW}══════════════════════════════════════════════════════${NC}"; echo -e "${YELLOW}  $*${NC}"; echo -e "${YELLOW}══════════════════════════════════════════════════════${NC}"; }

cleanup() {
  log "清理測試環境..."
  # 不關閉 daemon，那是常駐服務
  rm -f /tmp/agentos-pipeline-test-*.json
}

# ── Phase 0: 前提檢查 ─────────────────────────────────────────────────────

header "Phase 0: 前提檢查"

# 0.1 Node.js
if command -v node &>/dev/null; then
  pass "Node.js $(node -v)"
else
  fail "Node.js not found"
fi

# 0.2 Brave Browser
if [ -f "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" ]; then
  pass "Brave Browser installed"
else
  warn "Brave not found at default path (tests may fail)"
fi

# 0.3 提示詞檔案
if [ -f "$PROMPT_FILE" ]; then
  PROMPT_LINES=$(wc -l < "$PROMPT_FILE")
  pass "Prompt file exists ($PROMPT_LINES lines)"
else
  fail "Prompt file missing: $PROMPT_FILE"
fi

# 0.4 腦庫服務 (AgentOS API:8000)
if curl -s http://localhost:8000/health | grep -q '"ok":true'; then
  pass "AgentOS API running on :8000"
else
  warn "AgentOS API not running (brain write test will skip)"
  AGENTOS_OFFLINE=true
fi

# 0.5 super-engine scripts exist
if [ -f "$SCRIPT_DIR/super-engine/ask-daemon.ts" ]; then
  pass "ask-daemon.ts exists"
fi
if [ -f "$SCRIPT_DIR/super-engine/ask.ts" ]; then
  pass "ask.ts exists"
fi
if [ -f "$SCRIPT_DIR/super-engine/brave-profile" ] || [ -d "$SCRIPT_DIR/super-engine/brave-profile" ]; then
  pass "Brave profile directory exists"
else
  warn "Brave profile not found (may require login)"
fi

# 0.6 GenSpark API key (透過 settings.json 或環境變數)
GENSPARK_KEY=""
if [ -f "$SCRIPT_DIR/data/settings.json" ]; then
  GENSPARK_KEY=$(python3 -c "import json; d=json.load(open('$SCRIPT_DIR/data/settings.json')); print(d.get('api_keys',{}).get('genspark',''))" 2>/dev/null || echo "")
fi
if [ -n "$GENSPARK_KEY" ]; then
  pass "GenSpark API key found in settings"
else
  warn "No GenSpark API key in settings (GenSpark may require web login)"
fi


# ── Phase 1: Pipeline A — Daemon Warm ─────────────────────────────────────

header "Phase 1: Pipeline A — super-engine-warm daemon"

# 1.1 Daemon health check
DAEMON_HEALTH=$(curl -s http://127.0.0.1:$DAEMON_PORT/health 2>/dev/null || echo "unreachable")
if echo "$DAEMON_HEALTH" | grep -q '"ok":true'; then
  pass "Daemon healthy on :$DAEMON_PORT"
  DAEMON_RUNNING=true
else
  fail "Daemon not running on :$DAEMON_PORT (start with: node super-engine/ask-daemon.ts --port $DAEMON_PORT --profile super-engine/brave-profile)"
  DAEMON_RUNNING=false
fi

# 1.2 傳送提示詞（短版 — 用前 3000 字）
if [ "$DAEMON_RUNNING" = true ]; then
  log "Sending prompt to daemon (GenSpark / Opus route)..."

  # 寫成 temp JSON 避免 shell escaping 問題
  python3 -c "
import json
prompt = open('$PROMPT_FILE').read()[:3000]
print(json.dumps({'provider': 'genspark', 'prompt': prompt}))
" > /tmp/agentos-payload-daemon.json

  DAEMON_START=$SECONDS
  DAEMON_RESPONSE=$(curl -s --max-time $TIMEOUT \
    -X POST http://127.0.0.1:$DAEMON_PORT/ask \
    -H "Content-Type: application/json" \
    -d @/tmp/agentos-payload-daemon.json 2>&1 || echo '{"error":"timeout"}')
  DAEMON_ELAPSED=$((SECONDS - DAEMON_START))

  echo "$DAEMON_RESPONSE" > /tmp/agentos-pipeline-daemon.json

  # 解析結果
  DAEMON_OUTPUT=$(echo "$DAEMON_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('output','') or d.get('error','NO_OUTPUT'))" 2>/dev/null || echo "PARSE_FAILED")

  if echo "$DAEMON_OUTPUT" | grep -qi "NO_OUTPUT\|error\|PARSE_FAILED\|timeout"; then
    fail "Daemon response: ${DAEMON_OUTPUT:0:100}..."
    DAEMON_PASS=false
  else
    DAEMON_LEN=${#DAEMON_OUTPUT}
    pass "Daemon responded in ${DAEMON_ELAPSED}s ($DAEMON_LEN chars)"
    DAEMON_PASS=true
  fi
else
  DAEMON_PASS=false
fi


# ── Phase 2: Pipeline B — One-shot CLI ────────────────────────────────────

header "Phase 2: Pipeline B — super-engine one-shot CLI"

# 2.1 One-shot ask.ts（提示詞從檔案讀取）
if command -v node &>/dev/null; then
  log "Running ask.ts (GenSpark / Opus route)..."

  # 取提示詞前 3000 字，寫到 temp file
  python3 -c "
prompt = open('$PROMPT_FILE').read()[:3000]
open('/tmp/agentos-payload-cli.txt', 'w').write(prompt)
"

  CLI_START=$SECONDS
  # macOS has no `timeout`, use background + kill instead
  cd "$SCRIPT_DIR" && node super-engine/ask.ts \
    --provider genspark \
    --prompt "$(head -c 2000 /tmp/agentos-payload-cli.txt)" \
    > /tmp/agentos-pipeline-cli.json 2>&1 &
  CLI_PID=$!
  # wait up to TIMEOUT seconds with 1s polling
  for i in $(seq 1 $TIMEOUT); do
    if ! kill -0 $CLI_PID 2>/dev/null; then break; fi
    sleep 1
  done
  # if still alive after timeout, kill it
  if kill -0 $CLI_PID 2>/dev/null; then
    kill $CLI_PID 2>/dev/null || true
    echo '{"error":"timeout"}' > /tmp/agentos-pipeline-cli.json
  fi
  wait $CLI_PID 2>/dev/null || true
  CLI_ELAPSED=$((SECONDS - CLI_START))

  echo "$CLI_RESPONSE" > /tmp/agentos-pipeline-cli.json

  CLI_OUTPUT=$(echo "$CLI_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('output','') or d.get('error','NO_OUTPUT'))" 2>/dev/null || echo "PARSE_FAILED")

  if echo "$CLI_OUTPUT" | grep -qi "NO_OUTPUT\|error\|PARSE_FAILED\|timeout"; then
    fail "CLI response: $CLI_OUTPUT"
    CLI_PASS=false
  else
    CLI_LEN=${#CLI_OUTPUT}
    pass "CLI responded in ${CLI_ELAPSED}s ($CLI_LEN chars)"
    CLI_PASS=true
  fi
else
  fail "Node.js not available"
  CLI_PASS=false
fi


# ── Phase 3: 腦庫寫入 + 讀取回測試 ───────────────────────────────────────

header "Phase 3: 腦庫寫入 + 讀取回 (知識層傳遞)"

if [ "${AGENTOS_OFFLINE:-false}" != true ]; then
  # 3.1 寫入提示詞到腦庫
  log "Writing Opus review prompt to brain..."
  BRAIN_WRITE=$(curl -s -X POST 'http://localhost:8000/knowledge/protocol/opus-review-2026-06-20' \
    -H "Content-Type: application/json" \
    -d '{"content":"AgentOS 審查請求 - 給 Opus 的完整提示詞","metadata":{"domain":"architecture","type":"review-request","date":"2026-06-20","tags":["opus","review","agentos"]}}' 2>&1)
  echo "$BRAIN_WRITE" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('ok') or d.get('entry_id'), 'write failed'" 2>/dev/null && \
    pass "Prompt written to brain" || fail "Brain write failed: $BRAIN_WRITE"

  # 3.2 讀取回
  BRAIN_READ=$(curl -s 'http://localhost:8000/knowledge/protocol/opus-review-2026-06-20' 2>&1)
  echo "$BRAIN_READ" | python3 -c "import sys,json; d=json.load(sys.stdin); assert len(d.get('entries',[])) > 0" 2>/dev/null && \
    pass "Prompt read back from brain" || fail "Brain read failed"

  # 3.3 固化測試結果到腦庫（記憶固化端點試用）
  CONSOLIDATE_RESULT=$(curl -s -X POST http://localhost:8000/brain/consolidate \
    -H "Content-Type: application/json" \
    -d '{
      "experiences": [
        {
          "domain": "infrastructure",
          "type": "insight",
          "what": "測試 GenSpark (Opus) 雙管道傳遞：daemon warm vs one-shot CLI",
          "tags": ["pipeline-test", "genspark", "opus"]
        }
      ]
    }' 2>&1)
  echo "$CONSOLIDATE_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('ok')" 2>/dev/null && \
    pass "Test result consolidated to brain" || warn "Consolidate endpoint returned: $CONSOLIDATE_RESULT"
else
  warn "Skipping brain tests (AgentOS offline)"
fi


# ── Phase 4: 評估報告 ─────────────────────────────────────────────────────

header "評估報告"

echo ""
echo "  ${CYAN}管道 A (Daemon Warm)  管道 B (One-shot CLI)  腦庫${NC}"
echo "  ─────────────────────────────────────────────────────"

A_ICON="${GREEN}✅${NC}"; [ "$DAEMON_PASS" = false ] && A_ICON="${RED}❌${NC}"
B_ICON="${GREEN}✅${NC}"; [ "$CLI_PASS" = false ] && B_ICON="${RED}❌${NC}"

echo "  Delivery:    $A_ICON               $B_ICON"
echo "  Latency:     ${DAEMON_ELAPSED:-N/A}s               ${CLI_ELAPSED:-N/A}s"
echo ""

# 綜合評價
echo "  ── 綜合評價 ──"
echo ""

if [ "$DAEMON_PASS" = true ] && [ "$CLI_PASS" = true ]; then
  echo "  ${GREEN}兩條管道均成功送達 Opus。${NC}"
  echo "  Daemon warm 模式預期較快（瀏覽器常駐，零啟動），"
  echo "  適合頻繁調用；one-shot CLI 適合一次性的深度審查。"
elif [ "$DAEMON_PASS" = true ]; then
  echo "  ${YELLOW}僅 Daemon 模式成功。${NC}"
  echo "  日常使用推薦 daemon warm。若要從 Scream Code 直接呼叫，"
  echo "  可以透過 AgentOS executor registry 的 super-engine-warm type。"
elif [ "$CLI_PASS" = true ]; then
  echo "  ${YELLOW}僅 One-shot CLI 成功。${NC}"
  echo "  建議啟動 daemon 以獲得 28x 加速（2.3s vs 64s）。"
else
  echo "  ${RED}兩條管道均未成功。${NC}"
  echo "  可能原因："
  echo "  - GenSpark 需要先登入（node setup-profile.ts）"
  echo "  - Brave profile 過期"
  echo "  - GenSpark 封鎖 headless 瀏覽器"
fi

echo ""
echo "  ── 測試統計 ──"
echo "  通過: $PASS"
echo "  失敗: $FAIL"
echo "  ㊉  總計: $((PASS + FAIL)) 項檢查"
echo ""

# 最終結論
if [ $FAIL -eq 0 ]; then
  echo -e "  ${GREEN}🎯 結論：AgentOS 雙管道基礎設施正常運作。${NC}"
  exit 0
else
  echo -e "  ${YELLOW}⚠️  結論：有 $FAIL 項檢查未通過，請參考上方詳細資訊。${NC}"
  exit 1
fi
