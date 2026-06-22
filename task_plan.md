# AgentOS 推進規劃書

> 基於 v3 架構（Scream 計劃+執行、Claude CLI 驗收、AgentOS 基礎設施）
> 建立時間：2026-06-20 | 更新時間：2026-06-22 | 當前階段：Session C Scheduler 完成（自修復迴圈閉環）

---

## 目標

將 AgentOS 從「架構驗證完成」推進到「可日常使用」的 MVP 狀態。

---

## 已完成的事實

- [x] **v3 架構完整實作** — Scream 計劃+執行、Claude CLI 驗收、AgentOS 基礎設施
- [x] **executor registry** — register/get/list/run 四介面，三種 type（subprocess / super-engine / super-engine-warm）
- [x] **super-engine** — Playwright 驅動 Brave，GenSpark 13-27s + Gemini daemon 2.3s 🔥
- [x] **腦庫 SQLite+FTS5** — 22 項測試全過
- [x] **端到端測試** — test_e2e.py 14 項全過
- [x] **記憶固化** — consolidate protocol + /brain/consolidate + 測試
- [x] **協議模板庫** — 10+ 份協議（含 military-grade-sdlc、agnes-multimodal、skill-bridge）
- [x] **Phase 5 實戰驗證** — `/task/make` + GenSpark ✅、`/task/verify` pass/fail ✅
- [x] **MCP 搜尋工具接入** — DuckDuckGo HTML 解析器，純 stdlib，18 項測試 ✅
- [x] **Agnes 多模態 MCP** — 看圖/產圖/產影片，4 API endpoints，20 項測試 ✅
- [x] **Skill Bridge** — 自動掛載 Claude CLI 17 個 executable skill → 33 個 executor，9 項測試 ✅
- [x] **Session C Scheduler（自修復迴圈閉環）** — task_queue + runner（三停六分支）+ A 巡檢器 + B 佇列 API（`/queue/*`）+ Trigger 心跳 daemon（`heartbeat.py`）。系統會自己跑了。
- [x] **Session D Auto-Consolidate（自我成長）** — `orchestrator/auto_consolidate.py`：`/task/verify` 通過/撞線後自動萃取 gene 存 brain（pass→pattern / escalate→bug-fix，skip retry），best-effort 不破壞 verify，`settings.auto_consolidate` 可關。
- [x] **全測試通過** — 348 passed（21 個測試檔）

---

## 下一棒（依優先序）

### Session B: Model Router（成本控制）— 擱置

評估後判定多半已落地：`router/mapping.py` 按任務類型選模型 + `runner` 的 `cost_ledger`/撞線停。剩「預算低時降級」一小片，且會傷 architecture 品質。真量到成本痛再補 ~20 行，不當 Session 做。詳見 `.scream-code/optimization-report-2026-06-22.md`。

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
階段二完成 🎉  Session C Scheduler 完成 🎉  Session D Auto-Consolidate 完成 🎉
下一棒: 無硬性 — 跑起來看真實使用再定（Model Router 擱置）
Backlog: clarify_routing UI / headless / 沙箱 / Model Router
```

說明：核心四循環（safety/clarify/route/verify）+ 自修復迴圈（Scheduler）+ 自我成長
（Auto-Consolidate）皆已閉環。系統可自跑、自修、自記。下一步建議：讓 heartbeat 實跑一段，
用真實 trace 餵 OPTIMIZATION.md 的評測集，量出下一個值得投資的點。