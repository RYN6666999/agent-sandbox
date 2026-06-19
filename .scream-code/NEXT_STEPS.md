# AgentOS 下一步 — 實作提示詞

> 本文檔總結所有討論過的架構決策、角色定位、實作範圍，讓接手的 AI 或人可以直接開始。

---

## 一、核心願景

三個 CLI（Opus 網頁版、Scream Code、Claude Code）透過 AgentOS 辦公室統一調度協作，不靠手動切視窗、複製貼上。

| 角色 | 誰 | 優勢 | 限制 | 比喻 |
|---|---|---|---|---|
| **Planner + Maker** | **Scream Code** | 規劃、產出、判斷、跨角色溝通 | 活在 session 裡，不能常駐 server | Foxconn PM |
| **Checker** | **Claude CLI** | 真跑 pytest、程式碼審查、客觀驗收 | 用完即焚，無 session | QA 部門 |
| **Action (回圈層)** | **AgentOS** | safety gate、audit log、executor registry、腦庫 | 沒有智商，只有規則和設備 | NCC / 規章制度 |
| **顧問** | Opus 4.8 (GenSpark 網頁) | 最強戰略判斷、架構設計、品質把關 | 不能執行、只能透過 gbrain 溝通 | 蘋果董事會 |
| **小雜工** | Gemini (super-engine) | 廉價小任務：分類、摘要、提取 | 品質不穩定，不適合高風險任務 | 工讀生 |

### 三種協作模式

| 模式 | 工具 | 通訊方向 | 延遲 | 適合場景 |
|---|---|---|---|---|
| Async 戰略 | gbrain (Postgres + R2) | Opus ↔ Scream | 分鐘～小時 | 戰略方向、重大決策 |
| Sync 戰術 | super-engine (Playwright) | Scream → 網頁 LLM | 5～22 秒 | 即時判斷、戰術問題 |
| Execution | AgentOS (subprocess) | Scream → Claude Code | 秒～分鐘 | 寫程式、跑測試 |

---

## 二、已拍板的決策

### 路由策略：顯式指定 + fallback

- `TaskSpec.executor` 欄位已存在（`"litellm"` / `"claude-code"`）
- MVP 階段不做事前聰明路由，由 Scream 在派工時指定 executor
- registry 資料結構預留 `capabilities` 欄位，留給未來能力宣告路由

### 第一版接兩隻

- **Claude Code** — CLI subprocess spawn（已部分實作 `_make_via_claude_code()`）
- **super-engine** — 包成 executor registry 的一種，Playwright 開瀏覽器驅動網頁 LLM
- Scream 本身不進 registry（Scream 是規劃者，不是 executor）

### MVP 不做

- A2A full protocol（留階段四）
- MCP server 模式（留階段二）
- 聰明路由

---

## 三、架構圖（定稿）

```
Opus（董事）
  │ 寫入戰略 → gbrain
  │
  ├────────────────────── gbrain（會議記錄 ─ Postgres + R2）
  │                            ▲
  │                            │ 讀取
Scream Code（監督+規劃）
  │ 全程活著，有上下文
  │
  ├──→ HTTP ──→ AgentOS
  │               ├── executor registry
  │               │   ├── "claude-code"  →  subprocess → Claude Code
  │               │   └── "web-llm-xxx"   →  super-engine → 網頁 LLM
  │               ├── safety gate（規則攔截）
  │               ├── decision_log（審計）
  │               ├── Blackboard .sdd/（短期任務狀態）
  │               └── Checker（pytest 真跑）
  │
  ├──→ 結果判斷
  │      ├── 日常迭代 → 自行決定
  │      ├── 交付前審查 → 寫 gbrain → Opus
  │      └── 打回 → 讀 gbrain → 修正
  │
  └──→ 交付使用者
```

---

## 四、實作清單（按優先序）

### Phase 1：executor registry（核心骨架）✅

**目標**：把 `orchestrator/maker.py` 裡 `_make_via_claude_code()` 的 subprocess spawn 邏輯抽成通用的 registry pattern。

**狀態：已完成**（commit 待 push）

檔案：`orchestrator/executor_registry.py`（新增）

```python
# 介面
def register(defn: ExecutorDef) → None
def get(name: str) → ExecutorDef | None
def list() → list[ExecutorDef]
def run(name: str, prompt: str, *, timeout, on_token) → str
```

- `_make_via_claude_code()` 已移除，邏輯移到 registry.run()
- maker.py `if spec.executor == "claude-code"` 分支改走 registry
- settings.json 新增 `executors.claude-code.default_model` 覆蓋機制
- 4 個 unit test（register/get/list/unknown）通過

### Phase 1b：Blackboard HTTP API ✅

**目標**：讓 Scream 透過 HTTP 讀寫 `.sdd/`（用 Bash curl 呼叫 AgentOS API）。

**狀態：已完成**

檔案：`api/main.py`（新增端點）

```
GET  /blackboard/{key_prefix}   → 讀最新一筆（404 if none）
POST /blackboard/{key}          → 寫一筆（body: {"data": {...}}）
GET  /executors                 → 列出已註冊 executor
```

- 沿用現有 `orchestrator/blackboard.py` 底層，只加 HTTP wrapper
- 測試透過既有 blackboard test 驗證底層邏輯

### Phase 2：super-engine executor 整合 ✅

**目標**：把 super-engine 包進 executor registry。

**狀態：已完成**

```
agent-sandbox/super-engine/
├── ask-daemon.ts       # 🔥 Keep-warm HTTP server（推薦使用）
├── ask.ts              # One-shot CLI（備用）
├── config.js           # Provider 設定（genspark, gemini 兩條線路）
├── setup-profile.ts    # 一次性 Brave profile 設定（指紋登入）
├── login.ts            # 登入備用工具
├── extract_cookies.py  # Brave cookie 提取器
└── brave-profile/      # 🔑 已登入的 Brave profile
```

**兩條線路實測速度：**

| Provider | 模式 | 第一次 | 第二次（warm） |
|----------|------|--------|----------------|
| Gemini 免費版 | one-shot | 64s | — |
| Gemini 免費版 | **daemon warm** | **3.5s** | **2.3s** 🔥 |
| GenSpark (Opus 4.8) | one-shot | 27s | — |
| GenSpark (Opus 4.8) | **daemon warm** | **21s** | ~18s |

使用方式：
```bash
# 啟動 daemon（開一次瀏覽器即可常駐）
node super-engine/ask-daemon.ts --port 3456 --profile super-engine/brave-profile

# 發請求（瀏覽器已 warm，2-3s 回應）
curl -X POST http://localhost:3456/ask \
  -H "Content-Type: application/json" \
  -d '{"provider":"gemini","prompt":"解釋遞迴"}'

# 或透過 AgentOS /task/run
curl -X POST http://localhost:8000/task/run \
  -d '{"task":"解釋遞迴","executor":"web-llm-gemini"}'
```

**效能關鍵**：polling 1000ms→200ms、消除 launch+navigation 每次 3-5s、daemon 瀏覽器常駐零啟動。registry 支援 `type: "super-engine-warm"` 走 HTTP 連 daemon。`inspect-chat.ts` / `record.ts` / `capture-selectors.ts` / `dump-*.ts` 為調試用暫存檔，已清理。

### Phase 3b：腦庫 SQLite 整合 ✅

**目標**：建立真正的腦庫儲存層 — SQLite 知識庫 + 統一讀寫介面。

**狀態：已完成**

檔案：
- `orchestrator/knowledge.py` **新增** — write_knowledge / read_knowledge / search_knowledge(FTS5) / get_knowledge
- `api/main.py` **修改** — 新增 4 個 /knowledge 端點
- `scripts/agentos.sh` **修改** — 新增 knowledge-write / knowledge-read / knowledge-search 指令
- `tests/test_knowledge.py` **新增** — 19 項測試（CRUD + FTS + schema idempotency + metadata round-trip + slashes-in-key）

schema：
```sql
CREATE TABLE entries (id TEXT PK, key TEXT, content TEXT, metadata TEXT JSON, created_at TEXT, updated_at TEXT);
CREATE VIRTUAL TABLE entries_fts USING fts5(content, content=entries);
-- + triggers 保持 FTS5 與 entries 同步
```

**Claude Code 測試發現並修復 2 bug**：
1. 路由順序：wildcard `{key}` 吃掉 `/search` 和 `/id/`
2. key 含斜線：FastAPI 不吃 `/`，需 `{key:path}` + `redirect_slashes=False`

### Phase 3c：協議模板庫 ✅

**目標**：把 agent 之間的交互協議寫成系統提示詞，存進 AgentOS。

**狀態：已完成**

```
protocols/
├── README.md                       # Protocol 系統總覽
├── handoff-opus.md                 # Scream ↔ Opus gbrain 戰略交接
├── delegate-claude-code.md         # Scream → Claude Code 任務派工
├── delegate-subagent.md            # Scream → 小模型子代理
├── record-session.md               # Session 紀錄
├── review-request.md               # Opus 審查請求
├── task-breakdown.md               # 任務拆解
├── progress-report.md              # 進度報告
└── write-protocol.md               # Meta：如何寫協議
```

shell client 支援：
```bash
./agentos.sh protocol list          # 列出所有協議
./agentos.sh protocol show <name>   # 顯示協議內容
./agentos.sh protocol push <name>   # 推送到腦庫 (key: protocol/<name>)
```

### Phase 4：角色重構 v2 ✅

**目標**：重新定義五角色架構 — Scream (Planner+Maker)、Claude CLI (Checker)、AgentOS (Action 回圈層)、Opus (顧問)、Gemini (小雜工)。

**狀態：已完成**

核心變更：
| 檔案 | 變更 |
|---|---|
| `orchestrator/maker.py` | **簡化** — 收 TaskSpec → 查 registry → call LLM → 回傳。移除 MCP tool 細節 |
| `orchestrator/checker.py` | **改寫** — 移除 LLM 評分 fallback（_llm_check / _llm_score / litellm import），純 pytest + Claude CLI |
| `orchestrator/loop.py` | **改造** — 不再有 LangGraph 自動循環，改為 `run_verification()` 單次驗證函式 |
| `api/main.py` | **新增** `/task/make`（maker 端點）和 `/task/verify`（checker 端點）|
| `.scream-code/ARCHITECTURE.md` | **全面更新** — 新角色圖、新協作流程、AgentOS 最終邊界 |
| `protocols/delegate-claude-code.md` | **更新** — 從「通用 executor」改為「Checker 協議」|
| `protocols/delegate-subagent.md` | **更新** — 雙路徑：高價值走 AgentOS、低價值直接 call |

### Phase 4：Scream 端的 client ✅

**目標**：我在這個 session 裡用 Bash/curl 呼叫 AgentOS API。

**狀態：已完成**

```
curl -X POST http://localhost:8000/task/run \
  -H "Content-Type: application/json" \
  -d '{"task": "build cashflow calculator", "executor": "claude-code"}'
```

新增：
- `POST /task/run` 同步執行端點 — safety gate → loop → 回傳結果，blocking HTTP
- `scripts/agentos.sh` shell client — `run`, `blackboard-read`, `blackboard-write`, `executors`, `health`
- 4 個 unit test 全過（safety block / invalid executor / mock success / executor propagation）

---

## 五、關鍵檔案地圖（v2 角色重構後）

| 檔案 | 動作 |
|---|---|
| `orchestrator/maker.py` | **簡化** — thin wrapper：收 TaskSpec → 查 registry → call LLM → 回傳 |
| `orchestrator/checker.py` | **改寫** — 移除 LLM fallback，純 pytest + Claude CLI |
| `orchestrator/loop.py` | **改造** — 無 LangGraph，改為 `run_verification()` 單次驗證 |
| `api/main.py` | **新增** — `/task/make` 和 `/task/verify` 端點 |
| `api/main.py` | **修改** — `/task/run` 簡化為單次 maker call，保留相容 |
| `.scream-code/ARCHITECTURE.md` | **全面更新** — v2 五角色架構 |
| `protocols/delegate-claude-code.md` | **更新** — Checker 協議 |
| `protocols/delegate-subagent.md` | **更新** — 雙路徑（AgentOS / 直接 call）|

---

## 六、紅線

1. 不要重新設計 TaskSpec 或停損邏輯 — A2A 的 task state 跟你的停損是兩層東西
2. 每個 CLI 的 flag 要 `--help` 實測，不要憑記憶寫
3. 不把 gbrain 直接整合進 MVP（現有 gbrain 不動）
4. Scream 不進 executor registry（不當 executor）
