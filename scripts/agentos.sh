#!/bin/bash
# agentos.sh — Scream 端的 AgentOS API client
# 從 shell/curl 呼叫 AgentOS 的同步端點。
#
# 用法:
#   ./agentos.sh run "task description"
#   ./agentos.sh run --executor claude-code "debug this bug"
#   ./agentos.sh blackboard-read key_prefix
#   ./agentos.sh blackboard-write key_prefix '{"data": {"value": 42}}'
#   ./agentos.sh executors
#   ./agentos.sh health
#   ./agentos.sh --help
#
# 環境變數:
#   AGENTOS_URL  — AgentOS base URL（預設 http://localhost:8000）

set -euo pipefail

BASE="${AGENTOS_URL:-http://localhost:8000}"

usage() {
    cat <<EOF
用法: $(basename "$0") <command> [args...]

Commands:
  run [--executor litellm|claude-code] <task>  同步執行任務
  blackboard-read <key_prefix>                 讀黑板上最新一筆
  blackboard-write <key> <json>                寫一筆到黑板
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