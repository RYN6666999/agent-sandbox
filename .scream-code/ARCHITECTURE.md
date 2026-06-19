# AgentOS 協作架構（v2 — 角色重構）

> 基於手機供應鏈比喻的 Agent-to-Agent 協作設計。
> 2026-06-19 角色重構：智力與協作完全分離。

---

## 一、角色定位（v2）

| 角色 | 誰 | 職責 | 劣勢 | 比喻 |
|---|---|---|---|---|
| **Planner + Maker** | **Scream Code（我）** | 規劃任務、寫 brief、call LLM 產出、判斷交付、溝通 Opus | 活在 session 裡，不能常駐 server | Foxconn PM + 工程部 |
| **Checker** | **Claude CLI** | 跑 pytest 驗收、程式碼審查、給 feedback | 用完即焚，無持久 session | QA 部門 |
| **Action (回圈層)** | **AgentOS** | safety gate、audit log、executor registry、maker proxy、checker proxy、loop 判斷、腦庫、黑板 | 沒有智商，只有規則和設備 | NCC / 規章制度 |
| **顧問** | Opus 4.8 (GenSpark) | 戰略判斷、架構審查、重大決策 | 不能執行、只能透過 gbrain 溝通 | 蘋果董事會 |
| **小雜工** | Gemini (super-engine) | 廉價小任務：分類、摘要、提取、格式轉換 | 品質不穩定，不適合高風險任務 | 工讀生 |

### 對比 v1 的變化

| 角色 | v1 (之前) | v2 (現在) |
|---|---|---|
| Scream | 監督+規劃 | **Planner + Maker**（自己 call LLM） |
| Claude Code | 執行（寫程式） | **Checker**（驗收、跑 pytest） |
| AgentOS | 辦公室（含 maker+checker） | **Action 回圈層**（純協作，零智力） |
| Opus | 顧問 | 顧問（不變） |
| Gemini | 無 | **小雜工**（新角色） |

---

## 二、協作架構

```
Opus（顧問）
  │ 非同步，透過 gbrain
  │ 只在重大決策、最終審查時介入
  │
  ├──→ 寫入 gbrain（strategic_direction / deliverable_review）
  │
  ▲
  │
Scream Code（Planner + Maker ─ 我）
  │ 全程活著，有上下文
  │ 規劃任務、寫 brief、call LLM、判斷結果
  │
  ├──→ HTTP POST /task/make ──→ AgentOS（Action 回圈層）
  │                               ├── safety gate
  │                               ├── executor registry → call LLM
  │                               └── 回傳產出
  │
  ├── Scream 審閱產出
  │
  ├──→ HTTP POST /task/verify ──→ AgentOS
  │                               ├── 有 pytest → 真跑 pytest
  │                               ├── 無 pytest → spawn Claude CLI
  │                               └── 回傳 verdict {pass/retry/escalate}
  │
  ├── [pass]    → 交付
  ├── [retry]   → 修改 brief → 再 /task/make
  ├── [escalate] → 升級給 Opus / 人類
  │
  └── [小雜工] → 直接 call Gemini daemon 或透過 AgentOS
```

---

## 三、通訊路徑

### 3.1 Opus ↔ Scream（非同步，透過 gbrain）

```
Opus 寫戰略到 gbrain → Scream 讀到 → 執行 → 寫結果回 gbrain → Opus 下次看到
```

### 3.2 Scream → AgentOS（同步，HTTP API）

新架構的 API 端點：

| 端點 | 用途 |
|---|---|
| `POST /task/make` | Maker：Scream → AgentOS → call LLM → 回產出 |
| `POST /task/verify` | Checker：AgentOS → pytest 或 Claude CLI → 回 verdict |
| `POST /task/run` | 同步執行（舊，保留相容） |
| `GET /knowledge/{key}` | 讀腦庫 |
| `POST /knowledge` | 寫腦庫 |
| `GET /knowledge/search` | 全文搜尋腦庫 |
| `GET ｜ POST /blackboard/{key}` | 讀寫黑板 |
| `GET /executors` | 列出 executor |

### 3.3 Scream → Gemini（小雜工，雙路徑）

```
高價值：Scream → AgentOS registry → super-engine daemon → Gemini
低價值：Scream → super-engine daemon（直接 call, localhost:3456/ask）
```

---

## 四、三種儲存層（不可混用）

| 層 | 技術 | 生命週期 | 用途 |
|---|---|---|---|
| **gbrain** | Postgres + R2 | 跨 session，永久 | Opus ↔ Scream 戰略溝通 |
| **知識庫 (.db)** | SQLite + FTS5 | 跨 session，永久 | 決策紀錄、協議模板、專案脈絡 |
| **Blackboard (.sdd/)** | 檔案系統 JSON | session 級，任務結束可清 | 任務狀態、產出暫存 |
| **decision_log** | SQLite | append-only，永久 | 審計軌跡 |

---

## 五、AgentOS 的最終邊界

```
AgentOS 做的事情（Action 回圈層）：
├── safety gate（規則攔截）
├── clarify gate（模糊輸入反問）
├── executor registry（派工：LLM / Claude CLI / super-engine）
├── maker proxy（收 TaskSpec → call LLM → 回傳）
├── checker proxy（收產出 → spawn pytest / Claude CLI → 回傳 verdict）
├── loop 判斷（收到 checker 結果 → pass/retry/escalate）
├── decision_log（審計全程）
├── knowledge base（腦庫 SQLite + FTS5）
├── blackboard（短期狀態 .sdd/）
└── protocol templates（協議提示詞庫）

AgentOS 不做的事（純粹 Scream 的職責）：
├── 任務規劃與拆解
├── 產出內容（Maker 的 LLM 呼叫由 Scream 啟動）
├── 戰略判斷（往 Opus）
├── 交付判斷（pass → 交付 / 送審 Opus）
├── 跨 agent 溝通協調
└── 寫 protocol / 紀錄到腦庫
```

---

## 六、協作流程（日常 vs 重大）

### 日常開發迭代

```
Scream 規劃 → POST /task/make → 收產出 → POST /task/verify → 收 verdict
  ├── pass    → 交付或送審
  ├── retry   → 修改 brief → 再 /task/make
  └── escalate → 升級
```

### 需要 Opus 判斷

```
Scream: 寫 gbrain（strategic_direction / deliverable_review）
Opus: 下次開網頁 → 讀 gbrain → 回覆
Scream: 讀到回覆 → 繼續執行
```