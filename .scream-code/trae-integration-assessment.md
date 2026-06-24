# Scream ↔ Trae 接入評估

## 結論：可行，低成本，中等價值

Scream（透過 AgentOS）接入 Trae 在技術上完全可行，實作約 10 分鐘。

---

## 發現

### Trae CLI 支援 Headless Chat
```
trae chat -m ask|edit|agent [prompt]   # 支援 stdin 管線
trae chat -a <file>                     # 帶檔案上下文
trae chat --mode agent                  # Agent 模式（含 skill 調用）
```
版本 1.107.1，exit code 0，stdin 支援已驗證。

### Trae 已有 Skills
`~/.trae/skills/` 已裝 19 個 skill，包含 impeccable、debug、design、codebase-analysis 等。格式同 Claude Code（SKILL.md + frontmatter）。

### Trae 支援 MCP
擴充套件已裝 `juehangqin.vscode-mcp-server`，可作為 MCP client。

---

## 接入方式（目前不可行 — trae chat 無 stdout 輸出）

實測 `trae chat -m ask "prompt"`：
- Exit code 0
- stdout 為空（0 bytes）
- stderr 只印 "Reading from stdin via: /tmp/..."
- 不輸出回應內容 — chat 發生在 GUI 內部，不回 terminal

這跟 Claude Code 的 `-p`/`--print` 不同。Claude Code 會 block 到 LLM 回應完成再印 stdout；Trae 是「叫醒 GUI → 貼 prompt → 回 terminal」，不等回應。

### 唯一剩餘路徑：MCP + Extension Host

Trae 有完整的 extension host（已裝 `vscode-mcp-server` 擴充）。
如果 Trae 的 MCP server 能把 `trae chat` 的回應導到某個 stdio/HTTP 管道，就可以透過 MCP 接入。

但這前提是 Trae 必須先以 GUI 模式運行（extension host 活著），不能純 CLI。

### 記憶體測試結果

| 時點 | Trae 行程數 | 記憶體 |
|------|------------|--------|
| 執行前 | 18 | 676 MB |
| 執行中 | 20 | 889 MB (+213 MB) |
| 3 秒後 | 18 | 686 MB（釋放） |

記憶體是暫時性的，每次調用完釋放。但 676 MB baseline 意味 Trae 即使 idle 也在吃資源。

---

## 結論

`trae chat` 無 headless 輸出能力。不適合 AgentOS subprocess executor 模式。
可保留監測：當 Trae GUI 已開啟（extension host 活著）時，透過 MCP 工具繞路接入。

---

## 使用場景

| 場景 | 說明 | 適合 Option |
|------|------|------------|
| Scream 委派設計任務給 Trae（impeccable skill） | `run("trae-impeccable", "audit this header")` | B |
| 平行執行：Scream 寫 code + Trae 做 review | 兩個 executor 同時跑，省時間 | A |
| Trae agent 模式處理獨立專案 | `trae chat -m agent "建一個 React component"` | A |
| 讓 Trae 用自身模型當第二意見 | 避開單一 LLM 盲點 | A |

---

## 限制

1. **trae chat 無 `--print` / `--output-format`** — 輸出包含 ANSI、markdown frontmatter，需要額外 parse
2. **trae chat 會開 GUI 視窗** — 第一次會在 Dock 跳 icon，除非傳 `-n` 或 `-w` 控制
3. **Trae 模型由自身設定控制** — AgentOS 無法指定用哪個模型（不像 litellm executor 可設 model_flag）
4. **Cost 不透明** — 無 completion_cost 等效 API，無法記油表

---

## 建議順序

1. Option A → 註冊 `trae` executor → 驗證 stdin 輸出是否穩定 parse
2. 如果穩定 → Option B → 開 skill bridge 掃描 trae skill
3. 如果 parse 不穩定（ANSI 太多）→ 改包一層 wrapper script 濾掉非 JSON 輸出