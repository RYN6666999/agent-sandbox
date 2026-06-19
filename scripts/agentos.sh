#!/bin/bash
# agentos.sh — Scream 端的 AgentOS API client
# 從 shell/curl 呼叫 AgentOS 的同步端點。
#
# 用法:
#   ./agentos.sh run "task description"
#   ./agentos.sh run --executor claude-code "debug this bug"
#   ./agentos.sh blackboard-read key_prefix
#   ./agentos.sh blackboard-write key_prefix '{"data": {"value": 42}}'
#   ./agentos.sh knowledge-write <key> <content>
#   ./agentos.sh knowledge-read <key>
#   ./agentos.sh knowledge-search <query>
#   ./agentos.sh protocol list
#   ./agentos.sh protocol show <name>
#   ./agentos.sh protocol push <name>
#   ./agentos.sh executors
#   ./agentos.sh health
#   ./agentos.sh --help
#
# 環境變數:
#   AGENTOS_URL  — AgentOS base URL（預設 http://localhost:8000）

set -euo pipefail

BASE="${AGENTOS_URL:-http://localhost:8000}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROTOCOLS_DIR="${SCRIPT_DIR}/../protocols"

usage() {
    cat <<EOF
用法: $(basename "$0") <command> [args...]

Commands:
  run [--executor litellm|claude-code] <task>  同步執行任務
  blackboard-read <key_prefix>                 讀黑板上最新一筆
  blackboard-write <key> <json>                寫一筆到黑板
  knowledge-write <key> <content>              寫入知識條目
  knowledge-read <key>                         依 key 前綴讀取知識
  knowledge-search <query>                     全文搜尋知識
  protocol list                                列出可用協議模板
  protocol show <name>                         顯示協議模板內容
  protocol push <name>                         推送協議模板到腦庫
  executors                                    列出已註冊 executor
  health                                       健康檢查
  --help                                       顯示此說明

環境變數:
  AGENTOS_URL  AgentOS 基底 URL（預設 http://localhost:8000）
EOF
    exit 0
}

# ── run ────────────────────────────────────────────────────────────────────
cmd_run() {
    local executor="litellm"
    local task=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --executor) executor="$2"; shift 2 ;;
            *) task="$1"; shift ;;
        esac
    done

    if [[ -z "$task" ]]; then
        echo "❌ 缺少 task。使用 --help 查看用法。" >&2
        exit 1
    fi

    local body
    body=$(printf '{"task": %s, "executor": %s}' \
        "$(echo "$task" | jq -Rs '.' )" \
        "$(echo "$executor" | jq -Rs '.' )")

    echo "▶ 執行任務: ${task:0:60}..." >&2
    echo "  executor: $executor" >&2

    local result
    result=$(curl -s -X POST "$BASE/task/run" \
        -H "Content-Type: application/json" \
        -d "$body")

    local status
    status=$(echo "$result" | jq -r '.status // "error"')

    if [[ "$status" == "done" ]]; then
        echo "$result" | jq -r '.output // ""'
        local rounds final_score
        rounds=$(echo "$result" | jq -r '.rounds // 0')
        final_score=$(echo "$result" | jq -r '.final_score // ""')
        echo >&2 "✅ 完成 (${rounds} round(s), score: ${final_score:-N/A})"
    else
        echo "$result" | jq -r '.error // .status // "unknown error"' >&2
        exit 1
    fi
}

# ── blackboard-read ────────────────────────────────────────────────────────
cmd_blackboard_read() {
    local key="$1"
    if [[ -z "$key" ]]; then
        echo "❌ 缺少 key_prefix" >&2
        exit 1
    fi

    curl -s "$BASE/blackboard/$key" | jq .
}

# ── blackboard-write ───────────────────────────────────────────────────────
cmd_blackboard_write() {
    local key="$1"
    local data="$2"
    if [[ -z "$key" || -z "$data" ]]; then
        echo "❌ 用法: $(basename "$0") blackboard-write <key> <json>" >&2
        exit 1
    fi

    curl -s -X POST "$BASE/blackboard/$key" \
        -H "Content-Type: application/json" \
        -d "$data" | jq .
}

# ── knowledge-write ────────────────────────────────────────────────────────
cmd_knowledge_write() {
    local key="$1"
    local content="$2"
    if [[ -z "$key" || -z "$content" ]]; then
        echo "❌ 用法: $(basename "$0") knowledge-write <key> <content>" >&2
        exit 1
    fi

    local body
    body=$(printf '{"content": %s}' "$(echo "$content" | jq -Rs '.' )")

    curl -s -X POST "$BASE/knowledge?key=$(echo "$key" | jq -sRr @uri)" \
        -H "Content-Type: application/json" \
        -d "$body" | jq .
}

# ── knowledge-read ─────────────────────────────────────────────────────────
cmd_knowledge_read() {
    local key="$1"
    if [[ -z "$key" ]]; then
        echo "❌ 用法: $(basename "$0") knowledge-read <key>" >&2
        exit 1
    fi

    curl -s "$BASE/knowledge/$(echo "$key" | jq -sRr @uri)" | jq .
}

# ── knowledge-search ───────────────────────────────────────────────────────
cmd_knowledge_search() {
    local query="$1"
    if [[ -z "$query" ]]; then
        echo "❌ 用法: $(basename "$0") knowledge-search <query>" >&2
        exit 1
    fi

    curl -s "$BASE/knowledge/search?q=$(echo "$query" | jq -sRr @uri)" | jq .
}

# ── protocol ───────────────────────────────────────────────────────────────
cmd_protocol() {
    local subcmd="$1"
    shift || true

    case "$subcmd" in
        list)
            echo "可用協議模板 ($PROTOCOLS_DIR):"
            for f in "$PROTOCOLS_DIR"/*.md; do
                local name
                name=$(basename "$f" .md)
                local desc
                desc=$(head -5 "$f" | grep '^# ' | sed 's/^# //')
                printf "  %-25s %s\n" "$name" "${desc:-未命名}"
            done
            ;;
        show)
            local name="$1"
            if [[ -z "$name" ]]; then
                echo "❌ 用法: $(basename "$0") protocol show <name>" >&2
                exit 1
            fi
            local file="$PROTOCOLS_DIR/$name.md"
            if [[ ! -f "$file" ]]; then
                echo "❌ 找不到協議 '$name'。使用 'protocol list' 查看可用協議。" >&2
                exit 1
            fi
            cat "$file"
            ;;
        push)
            local name="$1"
            if [[ -z "$name" ]]; then
                echo "❌ 用法: $(basename "$0") protocol push <name>" >&2
                exit 1
            fi
            local file="$PROTOCOLS_DIR/$name.md"
            if [[ ! -f "$file" ]]; then
                echo "❌ 找不到協議 '$name'。使用 'protocol list' 查看可用協議。" >&2
                exit 1
            fi

            local content
            content=$(cat "$file")
            local body
            body=$(printf '{"content": %s}' "$(echo "$content" | jq -Rs '.' )")

            echo "▶ 推送協議 '$name' 到腦庫..." >&2
            curl -s -X POST "$BASE/knowledge?key=protocol/$name" \
                -H "Content-Type: application/json" \
                -d "$body" | jq .
            ;;
        *)
            echo "❌ 未知 protocol 子指令: $subcmd" >&2
            echo "可用: list, show, push" >&2
            exit 1
            ;;
    esac
}

# ── executors ──────────────────────────────────────────────────────────────
cmd_executors() {
    curl -s "$BASE/executors" | jq .
}

# ── health ─────────────────────────────────────────────────────────────────
cmd_health() {
    curl -s "$BASE/health" | jq .
}

# ── main dispatch ──────────────────────────────────────────────────────────
main() {
    if [[ $# -eq 0 ]]; then
        usage
    fi

    local cmd="$1"
    shift

    case "$cmd" in
        --help|-h) usage ;;
        run) cmd_run "$@" ;;
        blackboard-read) cmd_blackboard_read "$@" ;;
        blackboard-write) cmd_blackboard_write "$@" ;;
        knowledge-write) cmd_knowledge_write "$@" ;;
        knowledge-read) cmd_knowledge_read "$@" ;;
        knowledge-search) cmd_knowledge_search "$@" ;;
        protocol) cmd_protocol "$@" ;;
        executors) cmd_executors "$@" ;;
        health) cmd_health "$@" ;;
        *)
            echo "❌ 未知指令: $cmd" >&2
            echo "使用 --help 查看可用指令。" >&2
            exit 1
            ;;
    esac
}

main "$@"