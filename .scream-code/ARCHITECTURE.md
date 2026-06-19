# AgentOS 協作架構（v3 — 執行層重構）

> 基於手機供應鏈比喻的 Agent-to-Agent 協作設計。
> 2026-06-19 執行層重構：Scream 自己寫 code，AgentOS 退為純基礎設施。

---

## 一、角色定位（v3）

| 角色 | 誰 | 職責 | 劣勢 | 比喻 |
|---|---|---|---|---|
| **Planner + 執行者** | **Scream Code（我）** | 計劃任務、call LLM、寫 code、審閱產出、判斷交付、溝通 Opus | 活在 session 裡，不能常駐 server | Foxconn PM + 工程部自己焊板子 |
| **Checker** | **Claude CLI** | 跑 pytest 驗收、程式碼審查、給 feedback — **不寫 code** | 用完即焚，無持久 session | QA 部門（不碰烙鐵） |
| **Action (回圈層)** | **AgentOS** | safety gate、audit log、executor registry、checker proxy、腦庫、黑板 | 沒有智商，只有規則和設備 | NCC / 規章制度 |
| **顧問 / 可選執行層** | **Opus 4.8 (GenSpark)** | 戰略判斷、架構審查、重大決策、可選當執行層 | 需透過 super-engine 間接接入 | 蘋果董事會 |
| **小雜工** | **Gemini (super-engine)** | 廉價任務：摘要、分類、提取、格式轉換 | 僅文字，無法多模態 | 工讀生（只打字） |
| **多模態工具** | **Agnes (api)** | 看圖、產圖（agnes-image）、產影片（agnes-video）、廉價閒聊 | 文字品質不穩，不適合高風險任務 | 美編 + 總機 |

### 從 v2 到 v3 的關鍵變化

| 項目 | v2 | v3 |
|---|---|---|
| Scream | Planner + Maker（寫 brief → AgentOS call LLM） | **計劃 + 執行**：自己 call LLM、寫 code、判斷交付 |
| Opus | maker_model（web-llm-genspark 當執行層） | **可選執行層**（透過 super-engine 通路），或當顧問 |
| AgentOS | Action 層（含 maker proxy / checker proxy） | **基礎設施層**（無 maker proxy，但保留 executor registry） |
| `/task/make` | 主要路徑（Scream → AgentOS → LLM） | **雙路徑之一** — Scream 直接執行，或 POST /task/make 走 super-engine |
| 「maker 換強力模型」 | backlog | **可走雙路徑** — 加強 Scream 環境或 super-engine 通路 |

---

## 二、協作架構

```
Opus（顧問）
  │ 非同步，只透過 gbrain / super-engine
  │ 只在被諮詢時介入，不進日常產線
  │
  ├──→ gbrain（strategic_direction / deliverable_review）
  │
  ▲
  │
Scream Code（Planner + 執行者 ─ 我）
  │ 全程活著，有上下文
  │ 自己 call LLM、寫 code、審閱、判斷交付
  │ AgentOS 只提供基礎設施服務（非執行）
  │
  ├──→ 直接執行工作（Scream Code 環境內完成）
  │     ├── call LLM（透過 Scream Code 工具）
  │     ├── 寫 code、修改檔案
  │     ├── 跑命令、檢查結果
  │     └── 判斷是否可交付
  │
  ├──→ HTTP POST /task/verify ──→ AgentOS
  │                               ├── 有 pytest → 真跑 pytest
  │                               ├── 無 pytest → spawn Claude CLI（Checker）
  │                               └── 回傳 verdict {pass/retry/escalate}
  │
  ├── [pass]    → 交付
  ├── [retry]   → 修改後再驗
  ├── [escalate] → 升級給 Opus / 人類
  │
  ├──→ 腦庫讀寫（跨 session 記憶）
  │
  └── [小雜工] → 直接 call Gemini daemon 或透過 AgentOS
```

---

## 三、通訊路徑

### 3.1 Opus ↔ Scream（非同步，雙通路）

```
Opus 寫戰略到 gbrain → Scream 讀到 → 執行 → 寫結果回 gbrain → Opus 下次看到
Scream 也可透過 super-engine 通路直接諮詢 Opus（同步或半同步）
```

### 3.2 Scream → AgentOS（同步，HTTP API）

v3 的 API 端點 — 雙執行路徑：Scream 直接執行 或 POST /task/make 走 super-engine：

| 端點 | 用途 | 狀態 |
|---|---|---|
| `POST /task/verify` | Checker：AgentOS → pytest 或 Claude CLI → 回 verdict | **主要路徑** |
| `POST /task/run` | 同步執行（舊，保留相容） | 保留 |
| `GET /knowledge/{key}` | 讀腦庫 | 保留 |
| `POST /knowledge` | 寫腦庫 | 保留 |
| `GET /knowledge/search` | 全文搜尋腦庫 | 保留 |
| `GET \| POST /blackboard/{key}` | 讀寫黑板 | 保留 |
| `GET /executors` | 列出 executor（Checker / super-engine） | 保留 |
| `POST /task/make` | Scream → AgentOS → super-engine executor（Opus / Gemini） | 可用（第二執行路徑） |

### 3.3 Scream → Gemini / Agnes（小雜工 + 多模態工具）

```
文字雜工 → Gemini daemon（localhost:3456/ask，僅文字）
多模態任務 → Agnes API（看圖、產圖、產影片）
便宜閒聊  → Agnes-2.0-flash（converse 路徑）
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
AgentOS 做的事情（基礎設施層）：
├── safety gate（規則攔截）
├── clarify gate（模糊輸入反問）
├── executor registry（派工：Checker / super-engine）
├── checker proxy（收產出 → spawn pytest / Claude CLI → 回傳 verdict）
├── decision_log（審計全程）
├── knowledge base（腦庫 SQLite + FTS5）
├── blackboard（短期狀態 .sdd/）
└── protocol templates（協議提示詞庫）

AgentOS 不再做的事（v2 → v3 轉變）：
├── ✗ 自動 loop 判斷（pass/retry/escalate）—— Scream 自己判斷

AgentOS 不做的事（純粹 Scream 的職責）：
├── 任務規劃與拆解
├── 程式碼產出（Scream 自己 call LLM、寫 code）
├── LLM 呼叫（Scream 使用 Scream Code 環境中的工具直接完成，或可選 POST /task/make 走 super-engine）
├── 戰略判斷（往 Opus）
├── 交付判斷（pass → 交付 / 送審 Opus）
├── 跨 agent 溝通協調
└── 寫 protocol / 紀錄到腦庫
```

---

## 六、協作流程（日常 vs 重大）

### 日常開發迭代（v3）

```
Scream 規劃 → Scream 直接執行（call LLM + 寫 code）
  │
  ├──→ 自審、修改
  │
  ├──→ POST /task/verify → 收 verdict
  │       ├── pass    → 交付
  │       ├── retry   → 修改 → 再驗
  │       └── escalate → 升級 Opus / 人類
  │
  └──→ 記錄到腦庫（選擇性）
```

### 需要 Opus 判斷

```
Scream: 寫 gbrain（strategic_direction / deliverable_review）
        或透過 super-engine 通路直接諮詢
Opus:   下次開網頁 → 讀 gbrain → 回覆
        或回應即時諮詢
Scream: 讀到回覆 → 繼續執行
```
