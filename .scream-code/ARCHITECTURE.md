# CLI Cluster 協作架構草圖

> 基於手機供應鏈比喻的 Agent-to-Agent 協作設計。
> 台積電不做外殼、不做鏡頭 — 每家專精一件事，靠標準化介面拼在一起。

---

## 一、角色定位

> 先排每個角色的優勢與劣勢，再決定誰站什麼位置。

| 角色 | 誰 | 優勢 | 劣勢 | 比喻 |
|---|---|---|---|---|
| **董事** | Opus 4.8 (GenSpark 網頁) | 最強戰略判斷、品質把關、架構設計 | 不能執行、不能 spawn、只能透過 gbrain 溝通 | 蘋果董事會 |
| **監督+規劃** | **Scream Code（我）** | 有上下文、能調度工具、能串流程、能讀寫 gbrain | 活在 session 裡，不能常駐 server | Foxconn PM |
| **執行** | Claude Code | 寫程式、debug、跑測試、搜網路、瀏覽 | 用完即焚，無持久 session | 台積電產線 |
| **辦公室** | AgentOS | safety gate、audit log、pytest Checker、MCP 工具層 | 沒有智商，只有規則和設備 | NCC / 規章制度 |

---

## 二、協作架構

```
Opus（董事）
   │ 設定戰略方向，不參與日常迭代
   │ 只在重大決策、最終審查時介入
   │
   ├──→ 寫入 gbrain（會議記錄）
   │     「這個專案的架構方向是…」
   │     「某功能需要重構，評估方案」
   │     「最終交付品質審查：打回 / 放行」
   │
   ▼
gbrain（會議記錄 ─ Postgres + R2）
   │ 跨 session 持久知識層
   │ Opus 讀 / 寫，Scream 讀 / 寫
   │ 非同步：Opus 寫完關掉網頁，Scream 下次讀到
   │
   ▲
   │
Scream Code（監督+規劃 ─ 我）
   │ 全程活著，有上下文
   │ 讀 gbrain 取得戰略指示
   │ 規劃任務、拆解子任務、決定誰做
   │ 寫 gbrain 回報進度、請求 Opus 審查
   │
   ├──→ HTTP ──→ AgentOS（辦公室）
   │               ├── executor registry → 選誰做
   │               ├── spawn Claude Code subprocess
   │               ├── pytest Checker（客觀驗收）
   │               ├── safety gate / audit log
   │               └── .sdd/ Blackboard（短期任務狀態）
   │
   ├──→ 結果判斷
   │      ├── 日常迭代 → 我自己決定
   │      ├── 交付前審查 → 寫 gbrain → Opus 點頭才算過
   │      └── 打回 → 讀 gbrain 的 Opus 意見 → 修正
   │
   └──→ 交付給使用者
```

---

## 三、通訊路徑

### 3.1 Opus ↔ Scream（非同步，透過 gbrain）

這是**唯一的跨角色交接點**。情報斷層只有這裡一次：

```
Opus 寫戰略到 gbrain → Scream 讀到 → 執行 → Scream 寫結果回 gbrain → Opus 下次看到
```

gbrain 的資料結構範例：

```json
{
  "session": "專案_20260619",
  "from": "opus",
  "to": "scream",
  "type": "strategic_direction",
  "content": "這個 CLI 工具需要支援 plugin 架構，評估用 WASM 還是 Lua。設計方案寫好後送我看。",
  "status": "pending_review"   // pending / reviewed / rejected / done
}

{
  "session": "專案_20260619",
  "from": "scream",
  "to": "opus",
  "type": "deliverable_review",
  "content": "方案 A（WASM）實作完成，pytest 全過，架構圖已在 .scream-code/。請審查。",
  "status": "awaiting_approval"
}
```

### 3.2 Scream → AgentOS（同步，HTTP API）

Scream 透過 HTTP 呼叫 AgentOS 端點：

```
POST /chat                      # 提交任務（帶著 executor 指定）
POST /task/submit               # 提交子任務
GET  /task/{session_id}         # 查任務狀態/結果
POST /check                     # 觸發 Checker 驗收
GET  /blackboard/{key}          # 讀共享狀態
POST /blackboard                # 寫共享狀態
GET  /decision_log/{request_id} # 讀審計鏈
```

### 3.3 AgentOS → Claude Code（同步，CLI subprocess）

AgentOS 維護一個 **executor registry**，每個 entry：

```python
{
  "name": "claude-code",
  "binary": "/Users/ryan/.local/bin/claude",
  "flags": ["--print", "-p"],
  "timeout": 300,
  "model_flag": "--model",
  "default_model": "claude-sonnet-4-6",
  "capabilities": {
    "can_write_code": true,
    "can_search_web": true,
    "can_run_tests": true,
    "can_browse": true
  }
}
```

AgentOS 收到 Scream 的任務 → 查 `TaskSpec.executor` → registry 找到對應 executor → spawn subprocess → stdout 解析 → 結果寫回 Blackboard。

---

## 四、三種儲存層（不可混用）

| 層 | 技術 | 生命週期 | 用途 |
|---|---|---|---|
| **gbrain** | Postgres + R2 | 跨 session，永久 | Opus ↔ Scream 戰略溝通、會議記錄、審查意見 |
| **Blackboard (.sdd/)** | 檔案系統 JSON | session 級，任務結束可清 | 任務狀態、Claude 產出、Checker 結果 |
| **decision_log** | SQLite | append-only，永久 | 審計軌跡、誰做了什麼決策 |

---

## 五、協作流程（日常 vs 重大）

### 日常迭代（Scream 自行決定）

```
Scream 規劃 → HTTP → AgentOS spawn Claude → Checker 驗收
     │                                              │
     │ ←──────── 合格（pytest 過）───────────────
     │
     ├── 寫 gbrain 通知 Opus：「已完成，待審查」
     └── 或直接交付使用者（低風險任務）
```

### 重大決策（需要 Opus 介入）

```
Scream: 需要 Opus 判斷
  │ 寫 gbrain：「這個架構方案有兩個選擇，請指方向」
  │
Opus: 下次開網頁 → 讀 gbrain → 回覆戰略方向
  │ 寫 gbrain：「選方案 A，但注意 XXX 邊界條件」
  │
Scream: 讀到 Opus 回覆 → 繼續執行
```

---

## 六、MVP 範圍

做三件事：

1. **AgentOS executor registry** — 把 `_make_via_claude_code()` 抽成 registry pattern
2. **Blackboard HTTP API** — 現有 `.sdd/` 加 HTTP 讀寫端點
3. **Scream 端的 client** — 我透過 Bash/curl 呼叫 AgentOS API

**不做：**
- 不做 A2A full protocol
- 不做 MCP server 模式
- 不做聰明路由（MVP 顯式指定 executor 就好）
- 不做 gbrain 直接整合（現有 gbrain 不動，先讓 Scream 能透過 API 寫 gbrain）

---

## 七、跟現有架構的接合點

| 現有元件 | 用在這版的方式 |
|---|---|
| `api/main.py` | 新增 /blackboard 端點，/chat 擴充 executor registry 支援 |
| `orchestrator/maker.py` | `_make_via_claude_code()` 抽成 registry general pattern |
| `orchestrator/blackboard.py` | 加 HTTP wrapper（file-based 保留） |
| `contracts/task_spec.py` | `executor` 欄位擴充支援更多 executor |
| `orchestrator/decision_log.py` | 不變，全程錄 |
| `orchestrator/safety.py` | 不變，每步過閘 |