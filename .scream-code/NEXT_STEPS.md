# AgentOS 下一步 — 實作提示詞

> 本文檔總結所有討論過的架構決策、角色定位、實作範圍，讓接手的 AI 或人可以直接開始。

---

## 一、核心願景

三個 CLI（Opus 網頁版、Scream Code、Claude Code）透過 AgentOS 辦公室統一調度協作，不靠手動切視窗、複製貼上。

| 角色 | 誰 | 優勢 | 限制 | 比喻 |
|---|---|---|---|---|
| **董事** | Opus 4.8 (GenSpark 網頁) | 最強戰略判斷、架構設計、品質把關 | 不能執行、只能透過 gbrain 溝通 | 蘋果董事會 |
| **監督+規劃** | Scream Code | 有上下文、能調度工具、能串流程 | 活在 session 裡，不能常駐 server | Foxconn PM |
| **執行** | Claude Code | 寫程式、debug、跑測試、搜網路 | 用完即焚，無 session | 台積電產線 |
| **辦公室** | AgentOS | safety gate、audit log、pytest Checker、MCP | 沒有智商，只有規則和設備 | NCC / 規章制度 |

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

### Phase 3：Scream 端的 client ✅

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

## 五、關鍵檔案地圖

| 檔案 | 動作 |
|---|---|
| `orchestrator/executor_registry.py` | **新增** — registry 核心 |
| `orchestrator/maker.py` | **修改** — `_make_via_claude_code()` 改寫成呼叫 registry.run() |
| `api/main.py` | **修改** — 新增 /blackboard 端點 |
| `api/main.py` | **修改** — /chat 端點讀 executor registry |
| `contracts/task_spec.py` | **確認** — executor 欄位是否存在 |
| `data/settings.json` | **修改** — 加入 executor registry 設定 |
| `.scream-code/ARCHITECTURE.md` | **留存** — 架構藍圖 |
| `CLAUDE.md` | **留存** — 協作規則 |

---

## 六、紅線

1. 不要重新設計 TaskSpec 或停損邏輯 — A2A 的 task state 跟你的停損是兩層東西
2. 每個 CLI 的 flag 要 `--help` 實測，不要憑記憶寫
3. 不把 gbrain 直接整合進 MVP（現有 gbrain 不動）
4. Scream 不進 executor registry（不當 executor）
