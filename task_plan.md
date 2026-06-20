# AgentOS 推進規劃書

> 基於 v3 架構（Scream 計劃+執行、Claude CLI 驗收、AgentOS 基礎設施）
> 建立時間：2026-06-20 | 當前階段：階段一收尾 + 階段二啟動

---

## 目標

將 AgentOS 從「架構驗證完成」推進到「可日常使用」的 MVP 狀態。

---

## 已完成的事實（本 session 驗證）

- [x] **`/task/make` + web-llm-genspark (Opus/GenSpark)** — 13.5s 正常回應 ✅
- [x] **`/task/verify` + pytest 真跑** — pass (10.0) / fail (2.0 + feedback) ✅
- [x] **ask.ts Brave path 修正** — `launchPersistentContext` 補上 `executablePath`
- [x] **maker.py executor routing 修正** — 當 maker_model 是 executor 時走 registry
- [x] **文件刺眼用語清除** — ARCHITECTURE.md / PROJECT.md / DECISIONS.md 等 6 檔

---

## 階段一收尾（核心細胞驗證完成）

### 1.1 更新 PROJECT.md 標記階段一完成

| 動作 | 檔案 | 說明 |
|------|------|------|
| 階段一狀態改為 ✅ | PROJECT.md | L235「階段一：核心細胞驗證（現在）」→「（已完成）」 |
| 新增 v3 實戰驗證項目 | PROJECT.md L189 | 加入 `/task/make` + `/task/verify` 實測成功的記錄 |
| 確認 backlog 優先序 | PROJECT.md L224 | 重新排列，TUI 拉最高優先 |

### 1.2 寫一份端到端測試案例

寫一隻 test script 同時測兩條路徑，確保未來改動不 regression：

| 測試 | 內容 | 預期 |
|------|------|------|
| `test_maker_super_engine` | POST /task/make → web-llm-genspark | output 非空 |
| `test_verify_pytest_pass` | POST /task/verify + 正確 code | status=pass, score=10.0 |
| `test_verify_pytest_fail` | POST /task/verify + buggy code | status=retry, score=2.0 |
| `test_verify_no_test` | POST /task/verify + 純文字 | source=claude-cli |

---

## 階段二啟動（基礎設施強化）

### 2.1 AgentOS TUI（最高優先）

取代廢棄的 React desktop app。用 terminal UI：

| 功能 | 優先級 | 說明 |
|------|--------|------|
| 任務列表 | P0 | 看到 /task 的歷史與狀態 |
| 腦庫瀏覽 | P0 | 讀寫 knowledge base |
| 驗收結果 | P1 | 看到 verify 的 pass/fail 歷史 |
| Executor 狀態 | P1 | 看到 registry 裡誰活著 |

技術方向：Python 原生 TUI（textual 或 rich）或參考 GASP skill 的 terminal animation。

### 2.2 MCP 搜尋工具接入

Roadmap 階段二的「第一個接搜尋工具」：

| 動作 | 說明 |
|------|------|
| 研究 Scream Code 支援的 MCP server | 確認可掛 search tool |
| 實作搜尋 executor | 包裝成 executor registry 的一員 |

### 2.3 Agnes 多模態 MCP（低優先）

D18 提到的 Agnes 看圖/產圖能力，掛成 MCP tool。但這需要 Agnes API key 和接線測試。

---

## Backlog（排程中不執行）

| 項目 | 原因 |
|------|------|
| super-engine headless | GenSpark 封鎖 headless，繞過成本高 |
| 真沙箱隔離 | 需要 Docker，違反 MVP 禁用清單 |
| frontend clarify_routing UI | TUI 先取代 React，此項併入 TUI |

---

## 優先序建議

```
P0: TUI 啟動（沒 UI 展示不了價值）
P1: 端到端測試（不寫 test 以後會後悔）
P2: 更新 PROJECT.md 階段狀態
P3: MCP search tool
P4: Agnes 多模態
Backlog: headless / 沙箱
```