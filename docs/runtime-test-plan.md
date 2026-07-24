# AgentOS Runtime — 20 任務驗證

## 目標
用 20 個真實任務測試整個 pipeline（input → context → execute → output → gate → log），
找出斷點、修復、優化，讓 Runtime 真的能落地。

## 分類覆蓋

| 路由 | 任務數 | 測試項目 |
|------|--------|---------|
| code (codebase-memory-mcp) | 5 | 架構查詢、呼叫追蹤、死碼檢測 |
| research (OpenCLI) | 3 | 站點查詢、瀏覽器操作 |
| compression (caveman-ponytail) | 3 | 輸出壓縮、CCR 召回 |
| gate (skill-security / format-validator) | 3 | 安全掃描、格式驗證 |
| context (brain) | 3 | MemoryWrite / Lookup / 雙寫 |
| session (agentsview) | 2 | Session 記錄查詢 |
| pipeline orchestration | 1 | 跨工具鏈 |

任務 01 — 10：第一輪（快速驗證各路由可通）
任務 11 — 15：第二輪（跨工具鏈 + pipeline）
任務 16 — 20：第三輪（邊界條件 + 容錯）
