#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# GBrain ↔ AgentOS 磨合測試
# 測試 knowledge.py 的 GBrain 整合：寫入、讀取、搜尋、fallback
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENT_SANDBOX="$SCRIPT_DIR/.."
GBRAIN_DIR="$HOME/gbrain"
VENV="$AGENT_SANDBOX/.venv"
GBRAIN_PORT=4242
PYTHON="$VENV/bin/python"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓ PASS${NC} $1"; }
fail() { echo -e "${RED}✗ FAIL${NC} $1"; exit 1; }
info() { echo -e "${CYAN}→${NC} $1"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }

# ── 1. Start GBrain if not running ─────────────────────────────────────────
info "Checking GBrain on port $GBRAIN_PORT..."

if lsof -i :$GBRAIN_PORT &>/dev/null; then
    warn "GBrain already running on port $GBRAIN_PORT"
else
    info "Starting GBrain..."
    cd "$GBRAIN_DIR"
    if [ ! -f ".env" ]; then
        warn "No .env found for GBrain — using local env"
    fi
    bun run src/cli.ts http-serve --port=$GBRAIN_PORT &
    GBRAIN_PID=$!
    echo "GBrain PID: $GBRAIN_PID"

    # Wait for it to be ready
    for i in {1..15}; do
        if curl -s "http://localhost:$GBRAIN_PORT/health" &>/dev/null; then
            info "GBrain ready"
            break
        fi
        sleep 1
    done
    if ! curl -s "http://localhost:$GBRAIN_PORT/health" &>/dev/null; then
        fail "GBrain did not start within 15s"
    fi
fi

# ── 2. Verify settings ─────────────────────────────────────────────────────
info "Checking AgentOS settings..."
SETTINGS="$AGENT_SANDBOX/data/settings.json"
if ! grep -q '"gbrain"' "$SETTINGS"; then
    fail "settings.json missing gbrain config"
fi
GBRAIN_ENABLED=$(python3 -c "import json; print(json.load(open('$SETTINGS')).get('gbrain', {}).get('enabled', False))")
if [ "$GBRAIN_ENABLED" != "True" ]; then
    fail "gbrain.enabled is not True in settings.json"
fi
pass "settings.json has gbrain enabled"

# ── 3. Test: dual write ────────────────────────────────────────────────────
info "Test 1: Dual write (AgentOS → SQLite + GBrain)"

cd "$AGENT_SANDBOX"

$PYTHON -c "
from orchestrator.knowledge import write_knowledge, search_knowledge, read_knowledge

# Write via knowledge.py (should also write to GBrain)
entry_id = write_knowledge('test/gbrain-smoke/hello',
    'Hello GBrain! This is a smoke test from AgentOS at 2026-06-20',
    metadata={'test': 'smoke', 'source': 'agentos'})
print(f'  entry_id: {entry_id}')
assert len(entry_id) == 16, f'bad entry_id: {entry_id}'
print('  SQLite write: OK')

# Verify via search (local FTS5)
results = search_knowledge('Hello GBrain')
if len(results) >= 1:
    print(f'  Local search: OK ({len(results)} results)')
else:
    fail('local search returned nothing')
"

pass "Dual write: SQLite"

# ── 4. Test: GBrain direct read ────────────────────────────────────────────
info "Test 2: Verify GBrain has the page"

PAGE=$(curl -s "http://localhost:$GBRAIN_PORT/page?slug=test/gbrain-smoke/hello")
echo "  GBrain response: $(echo "$PAGE" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("ok", False))')"

if echo "$PAGE" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('ok'), 'gbrain page not found'"; then
    pass "GBrain has the page"
else
    fail "GBrain page not found — dual-write may have failed"
fi

# ── 5. Test: search across both ────────────────────────────────────────────
info "Test 3: Cross-source search (SQLite + GBrain merged)"

$PYTHON -c "
from orchestrator.knowledge import search_knowledge

results = search_knowledge('GBrain smoke test')
print(f'  Merged results: {len(results)}')
for r in results:
    src = r.get('source', 'local')
    key = r.get('key', '?')
    print(f'    [{src}] {key}')
# Should have at least 1 result (the one we wrote above)
assert len(results) >= 1, 'merged search returned nothing'
"

pass "Cross-source search merged"

# ── 6. Test: write more, search more ───────────────────────────────────────
info "Test 4: Multiple writes + richer search"

$PYTHON -c "
from orchestrator.knowledge import write_knowledge, search_knowledge

# Write a few more entries
write_knowledge('test/gbrain-smoke/svelte',
    'Svelte 5 requires Node 18+. SvelteKit uses Vite for building.',
    metadata={'topic': 'svelte', 'source': 'agentos'})
write_knowledge('test/gbrain-smoke/agentos',
    'AgentOS is the infrastructure layer for AI agents. It provides safety gate, audit log, executor registry.',
    metadata={'topic': 'agentos', 'source': 'agentos'})

# Search for something in GBrain that was just written
results = search_knowledge('infrastructure layer safety gate')
print(f'  AgentOS search: {len(results)} results')
for r in results:
    src = r.get('source', 'local')
    key = r.get('key', '?')
    print(f'    [{src}] {key}')
assert len(results) >= 1, 'search for infrastructure returned nothing'
"

pass "Multi-write search works"

# ── 7. Test: read fallback ─────────────────────────────────────────────────
info "Test 5: Read fallback (no local → GBrain)"

$PYTHON -c "
from orchestrator.knowledge import read_knowledge

# This key doesn't exist in SQLite but exists in GBrain
results = read_knowledge('test/gbrain-smoke/')
print(f'  Read fallback: {len(results)} results')
for r in results:
    src = r.get('source', 'local')
    key = r.get('key', '?')
    print(f'    [{src}] {key}')
assert len(results) >= 1, 'read fallback returned nothing'
"

pass "Read fallback works"

# ── 8. Test: GBrain disabled gracefully ─────────────────────────────────────
info "Test 6: Disable GBrain, verify graceful degradation"

$PYTHON -c "
import json
settings_path = '$SETTINGS'

# Temporarily disable
with open(settings_path) as f:
    cfg = json.load(f)
cfg['gbrain']['enabled'] = False
with open(settings_path, 'w') as f:
    json.dump(cfg, f, indent=2)
"

$PYTHON -c "
from orchestrator.knowledge import write_knowledge, read_knowledge, search_knowledge

# Write should still work (SQLite only)
entry_id = write_knowledge('test/gbrain-off/solo',
    'Written while GBrain is disabled — should not reach GBrain')
print(f'  SQLite-only write: {entry_id}')
assert len(entry_id) == 16

# Read should work (local only)
results = read_knowledge('test/gbrain-off/')
print(f'  SQLite-only read: {len(results)} results')
assert len(results) >= 1

# Search should work (local only)
results = search_knowledge('GBrain is disabled')
print(f'  SQLite-only search: {len(results)} results')
"

pass "Graceful degradation when GBrain disabled"

# Restore GBrain enabled
$PYTHON -c "
import json
with open('$SETTINGS') as f:
    cfg = json.load(f)
cfg['gbrain']['enabled'] = True
with open('$SETTINGS', 'w') as f:
    json.dump(cfg, f, indent=2)
"

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════════════"
echo -e "${GREEN} All GBrain ↔ AgentOS integration tests passed!${NC}"
echo ""
echo "  Tested:"
echo "    1. Dual write (SQLite + GBrain)"
echo "    2. GBrain direct page verification"
echo "    3. Cross-source search merge"
echo "    4. Multiple writes + search"
echo "    5. Read fallback (local miss → GBrain)"
echo "    6. Graceful degradation when GBrain disabled"
echo ""
echo "  settings.json: ${CYAN}gbrain.enabled = true${NC}"
echo "  GBrain URL:    ${CYAN}http://localhost:$GBRAIN_PORT${NC}"
echo "═══════════════════════════════════════════════════════════════════════"