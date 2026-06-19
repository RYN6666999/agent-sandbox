# Shared CLI Config 提案 — 讓不同 CLI 共享已安裝資源

## 問題

Claude Code 已裝的 skill、MCP server、project context，Scream Code 看不到。
反過來也一樣。各自維護一份 = 重複投資。

## 解法：腦庫作為統一設定中心

不是取代各 CLI 自己的設定檔，而是**多一個同步源**：

```
┌──────────────────────┐
│    腦庫（知識庫）      │ ← 單一事實源
│  shared-config/       │
│  ├── mcp-servers/     │ ← MCP server 定義
│  ├── skills/          │ ← skill 清單與路徑
│  ├── project-rules/   │ ← AGENTS.md 級規則
│  └── tool-paths/      │ ← 共用工具路徑
└────────┬─────────────┘
         │ 同步
    ┌────┴────┐
    │         │
    ▼         ▼
┌────────┐ ┌────────┐
│Claude  │ │Scream  │
│Code    │ │Code    │
│.claude/│ │.agents/│
└────────┘ └────────┘
```

## 實作方式

### 1. 腦庫 key 命名規則

```
shared/cli/mcp/{server_name}     → {"command": "npx", "args": ["..."], "env": {...}}
shared/cli/skills/{skill_name}   → {"path": "~/.agents/skills/...", "type": "scream|claude"}
shared/cli/tools/{tool_name}     → {"path": "/opt/homebrew/bin/...", "version": "x.y"}
shared/cli/rules/{project}       → {"agents_md": "...", "model_pref": "deepseek"}
```

### 2. Hook 腳本（各 CLI 各自的同步腳本）

每個 CLI 安裝一個小 hook，啟動時從腦庫拉最新設定：

```bash
# ~/.agents/sync-config.sh（Scream Code 版）
# 啟動時自動執行
curl -s http://localhost:8000/knowledge/shared/cli | jq '.entries[] | .key' | while read key; do
  # 根據 key 類型同步到本機設定
done
```

### 3. 寫入端

任何 CLI 安裝新東西時，同時寫入腦庫：

```bash
# Claude Code 裝了新 MCP server
# 除了寫 ~/.claude/config/，也寫腦庫
curl -X POST "http://localhost:8000/knowledge?key=shared%2Fcli%2Fmcp%2Fmy-server" \
  -H "Content-Type: application/json" \
  -d '{"content": "{\"command\": \"npx\", \"args\": [\"...\"]}", "metadata": {"source": "claude-code"}}'
```

## MVP 範圍（先做最小可用）

| 功能 | 說明 | 複雜度 |
|------|------|--------|
| MCP server 共享 | Claude Code 裝的 MCP，Scream 也能用 | 低（純 brain 讀寫） |
| skill 清單查詢 | 知道對方裝了什麼 skill | 低（brain read） |
| 工具路徑共享 | brew、node、python 路徑互通 | 低（一次性寫入） |

## 不做（MVP）

- 雙向即時同步（太複雜）
- 自動衝突解決（先寫入者贏）
- skill 格式轉換（先各自維護，後續再自動映射）

## 一句話

> **腦庫不只是記對話，更是 CLI 生態的「DNS + 設定中心」。裝一次，到處可用。**