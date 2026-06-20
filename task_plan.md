# AgentOS 推進規劃書

> 基於 v3 架構（Scream 計劃+執行、Claude CLI 驗收、AgentOS 基礎設施）
> 建立時間：2026-06-20 | 更新時間：2026-06-20 | 當前階段：階段一已完成，階段二啟動中

---

## 目標

將 AgentOS 從「架構驗證完成」推進到「可日常使用」的 MVP 狀態。

---

## 已完成的事實

- [x] **v3 架構完整實作** — Scream 計劃+執行、Claude CLI 驗收、AgentOS 基礎設施
- [x] **executor registry** — register/get/list/run 四介面，三種 type（subprocess / super-engine / super-engine-warm）
- [x] **super-engine** — Playwright 驅動 Brave，GenSpark 13-27s + Gemini daemon 2.3s 🔥
- [x] **腦庫 SQLite+FTS5** — 19 項測試全過
- [x] **協議模板庫** — 8 份 agent 交互提示詞
- [x] **Phase 5 實戰驗證** — `/task/make` + GenSpark ✅、`/task/verify` pass/fail ✅
- [x] **Agnes image/video executors 接入** — agnes-image / agnes-video 正式註冊
- [x] **文件同步** — PROJECT.md 階段狀態更新、TUI 決策反映、Backlog 重新排列
- [x] **線上線下對齊** — settings.json 還原、本地新增檔 push 到遠端

---

## 待辦（依優先序）

### P0: 端到端整合測試 🎯 當前

寫一隻 test script 同時測多條路徑，確保未來改動不 regression：

| 測試 | 內容 | 預期 |
|------|------|------|
| `test_maker_super_engine` | POST /task/make → web-llm-genspark | output 非空 |
| `test_verify_pytest_pass` | POST /task/verify + 正確 code | status=pass, score=10.0 |
| `test_verify_pytest_fail` | POST /task/verify + buggy code | status=retry, score=2.0 |
| `test_verify_no_test` | POST /task/verify + 純文字 | source=claude-cli |

### P1: 記憶固化執行

memory-consolidation-plan.md 已建立，待執行：
- 從 session 經驗中萃取基因
- 寫入腦庫作為永久知識

### P2: MCP 搜尋工具接入 ✅ 已完成

Roadmap 階段二的「第一個接搜尋工具」：
- 研究 Scream Code 支援的 MCP server
- 實作搜尋 executor，包裝成 executor registry 的一員

### P3: Agnes 多模態 MCP 接入 ✅ 已完成

Agnes 看圖/產圖/產影片能力掛成 MCP tool：
- orchestrator/agnes.py — analyze_image / generate_image / generate_video / get_video_status
- scripts/agnes-analyze.py / agnes-image.py / agnes-video.py — CLI wrapper
- settings.json — 註冊 agnes-analyze / agnes-image / agnes-video executor
- api/main.py — POST /vision/analyze, /image/generate, /video/generate + GET /video/status/{id}
- tests/test_agnes.py — 20 項測試全過
- protocols/agnes-multimodal.md — 多模態協議

---

## 已決定不做

| 項目 | 原因 |
|------|------|
| **AgentOS TUI** | NEXT_STEPS.md 決策：「TUI = 不需要做」。以 API + shell client 為主。 |
| **GASP skill 研究** | TUI 取消後不再需要參考 Browser-in-the-Loop 動畫。 |

---

## Backlog（排程中不執行）

| 項目 | 原因 |
|------|------|
| frontend clarify_routing UI | React desktop 已廢棄，TUI 也不做，此項擱置 |
| super-engine headless | GenSpark 封鎖 headless，繞過成本高 |
| 真沙箱隔離 | 需要 Docker，違反 MVP 禁用清單 |

---

## 優先序一覽

```
P0: 端到端測試（不寫 test 以後會後悔）
P1: 記憶固化執行（計劃已就緒）
P2: MCP search tool（讓 agent 能聯網）
P3: Agnes 多模態 MCP
Backlog: clarify_routing UI / headless / 沙箱
```
