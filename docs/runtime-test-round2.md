# AgentOS Runtime — Round 2: Cross-Tool & Edge Case Tests

## 設計原則
- 第一輪測「每個路由通不通」
- 第二輪測「路由之間怎麼配合」+「壞掉時會怎樣」

## Test Suite

### A. 跨專案知識圖譜（codebase-memory-mcp）
| # | Task | 預期 |
|---|------|------|
| 21 | agent-sandbox 比 scream-code 大多少？跨 repo 搜尋 | 15k vs 4k nodes, 跨 project 查詢 |
| 22 | fdd-crm 跟 agent-sandbox 有沒有共用函數？ | 無（不同語言/架構）|
| 23 | 在 4 個已 index 的專案裡找到所有叫 `dispatch` 的函數 | 4 個 project 各找到 dispatch |

### B. Brain Pipeline（brain + MemoryWrite）
| # | Task | 預期 |
|---|------|------|
| 24 | 寫 brain → 讀 brain → 搜尋 brain → 比對 | write/read/search 一致 |
| 25 | 同 key 重複寫 → 讀取最新版本 | 回傳最新 content |
| 26 | 搜尋不存在的 key → 回傳空結果（非 error） | `{"entries":[]}` |

### C. Cross-Tool Chain
| # | Task | 預期 |
|---|------|------|
| 27 | codebase-memory-mcp call chain → 摘要寫 brain → read 確認 | 3 步驟完整 pipeline |
| 28 | skill-security scan result → 寫 brain → agentsview 查得到 | scan result 可追溯 |

### D. OpenCLI 直接操作
| # | Task | 預期 |
|---|------|------|
| 29 | opencli hackernews top --limit 3 | 回傳 3 筆 HN 熱門 |
| 30 | opencli list | 列出已安裝的站點適配器 |

### E. 邊界條件
| # | Task | 預期 |
|---|------|------|
| 31 | brain write 空 content | 回傳 error（非 crash） |
| 32 | codebase-memory-mcp trace_path 不存在的函數 | 回傳 error 訊息 |
| 33 | 同 port 重複起 agentos server | 第二個 bind error 但第一個不受影響 |
| 34 | agentos.sh health 在 runtime.json 不存在時 | 提示 init 而非 crash |
| 35 | agentsview 查沒資料的日期範圍 | 回傳空結果（非 error） |

### F. Runtime 自我檢測
| # | Task | 預期 |
|---|------|------|
| 36 | agentos.sh init → runtime.json 包含所有 5 工具 | 5 tools 全部列出 |
| 37 | pipeline 定義順序 | input → context → output → gate → log |
| 38 | routes 定義對應 | code/codebase, security/skill-security 等 |
| 39 | init 後重新執行 → 不覆蓋既有資料（idempotent） | 重新 init 結果一致 |
| 40 | runtime.json 版本號 | v0.1.0 |