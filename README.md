# AgentOS — 多角色產線作業系統

> Scream 規劃與執行，Claude CLI 驗收，AgentOS 只做門禁與審計，
> Opus 當顧問（選用執行路徑），Gemini 跑雜工 — 每個人做自己擅長的事。

不是程式碼產生器，也不是聊天工具箱。五種角色協作：
**Scream（計劃+執行）**→ **Claude CLI（驗收）** 穿過 **AgentOS（安全閘道）**，
**Opus（顧問）** 只在設計階段給建議，**Gemini（雜工）** 處理廉價任務。
Maker/Checker 二元模型已升級為專業分工的產線架構。

---

## 四根支柱（不可妥協）

| 支柱 | 說明 |
|------|------|
| **真實驗收** | Checker 真的開 subprocess 跑 pytest，不接受 LLM 幻覺綠燈 |
| **懂得停** | 三種停損（達標 / 煞車 / 撞線），不無限燒 token |
| **危險紅線** | 破壞環境的指令（rm -rf、DROP TABLE…）規則先攔，不交給模型 |
| **決策可追溯** | 每步分流、派工、驗收寫進 SQLite 審計日誌 |

---

## 五角色協作架構（v3）

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   Scream Code（計劃 + 執行）                              │
│   └─ 自己 call LLM、寫 code、判斷交付                     │
│                                                         │
│   Claude CLI（僅驗收）                                    │
│   └─ 不寫 code，只跑 pytest + 審查                        │
│                                                         │
│   AgentOS（純 Action 回圈層 — 基礎設施，不參與智力判斷）      │
│   └─ safety gate / audit log / executor registry        │
│      / 腦庫 / 黑板 / 協議模板庫                            │
│                                                         │
│   Opus 4.8（GenSpark）— 顧問                              │
│   └─ 選用執行路徑，需要時才諮詢                            │
│                                                         │
│   Gemini（super-engine）— 小雜工（僅文字）                  │
│   └─ 摘要、分類、格式轉換等廉價任務，2.3s 回應              │
│                                                         │
│   Agnes（api）— 多模態工具                                 │
│   └─ 看圖（agnes-2.0-flash）、產圖、產影片                  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 技術棧

| 層 | 技術 |
|----|------|
| 後端框架 | FastAPI |
| 模型接入 | LiteLLM / 統一 alias 路由 |
| 資料結構 | Pydantic（TaskSpec 等契約） |
| 儲存 | SQLite（審計日誌 + 腦庫，MVP 禁用 Postgres/Redis） |
| 工具接入 | MCP / subprocess executor registry |
| 瀏覽器自動化 | Playwright + Brave（super-engine） |
| 前端 | API + shell client 為主（React/Tauri 已廢棄） |

（LangGraph 已棄用，改用 Scream 原生控制流程）

---

## 快速開始

### 後端

```bash
# 1. 複製環境變數範本並填入 API key
cp .env.example .env

# 2. 安裝依賴（Python 3.11+）
pip install fastapi litellm pydantic python-dotenv requests uvicorn websocket-client

# 3. 啟動 API server
uvicorn api.main:app --reload --port 8000
```

### super-engine — Gemini/GenSpark 瀏覽器自動化（dormant，預設不啟用）

> **預設路徑是 litellm（API key）。** super-engine 只是一條「用瀏覽器白嫖 GenSpark(Opus) /
> Gemini 免費版」的省錢選項，**核心自修復迴圈不依賴它**（`maker.make()` 預設走 litellm，
> `inspector → runner → checker → heartbeat` 完全不碰）。它也是全 repo 唯一脆的東西
> （網頁改版/封鎖即斷，headless 已被擋）。確定走付費 API 可整段移除。要啟用才跑：

```bash
cd super-engine
npm install
npx ts-node ask-daemon.ts   # keep-warm daemon，監聽 port 3456，Gemini ~2.3s
```

### Shell client

```bash
chmod +x scripts/agentos.sh
./scripts/agentos.sh health            # 健康檢查
./scripts/agentos.sh run "你的任務"     # 執行任務
./scripts/agentos.sh knowledge-read project/
./scripts/agentos.sh protocol list
```

### Scheduler 心跳 daemon（自修復迴圈）

```bash
# 定期喚醒 inspector + runner，系統自己跑
python -m orchestrator.heartbeat --interval 300   # 每 5 分鐘一拍
python -m orchestrator.heartbeat --once           # 只跑一拍（除錯）
```

### 測試

```bash
pytest tests/
# 340 passed（20 個測試檔）
```

---

## 關鍵檔案地圖

```
api/
  main.py                   # FastAPI 入口：所有 HTTP 端點
orchestrator/
  safety.py                 # 危險指令規則攔截（0 LLM calls）
  clarify.py                # 模糊輸入反問閘門
  checker.py                # 真跑 pytest 的驗收器
  loop.py                   # run_verification — 單次驗收回圈
  maker.py                  # executor 路由層
  executor_registry.py      # register/get/list/run 四介面（5 個內建 executor）
  decision_log.py           # SQLite 審計日誌（append-only）
  knowledge.py              # 腦庫（SQLite FTS5 + GBrain 雙寫）
  blackboard.py             # .sdd/ 檔案系統黑板
  model_registry.py         # alias → LiteLLM kwargs
  search.py                 # DuckDuckGo HTML 解析器（純 stdlib）
  agnes.py                  # Agnes 多模態 API 接入
  skill_bridge.py           # 自動掛載 .claude/skills/ 為 executor
  task_queue.py             # SQLite 佇列 + 狀態機 + cost_ledger 持久化油表
  runner.py                 # 三停六分支 run_loop（重啟後從 DB 重建油表）
  inspector.py              # A 巡檢器：跑本地 pytest，失敗去重後產任務入佇列
  heartbeat.py              # Trigger 心跳 daemon：定期喚醒 inspector + runner
router/
  classifier.py             # routing_intent()：3 向分類（answer/code/unclear）
  mapping.py                # 模型技能映射
contracts/
  task_spec.py              # TaskSpec Pydantic 定義
protocols/                  # 13 份 agent 交互提示詞模板
scripts/
  agentos.sh                # Shell client（Scream → AgentOS）
  search-web.py             # web-search executor CLI wrapper
  agnes-analyze/image/video.py  # Agnes executor CLI wrappers
super-engine/
  ask-daemon.ts             # Keep-warm HTTP daemon（port 3456，Gemini 2.3s）
  ask.ts                    # One-shot CLI 模式（備用）
data/
  settings.json             # 執行期設定（模型、executor、GBrain 等）
tests/                      # 340 tests，涵蓋所有模組
```

---

## 已實作功能（v3 完整狀態）

- [x] **v3 角色重構** — Scream 直接執行、AgentOS 純基礎設施、Claude CLI 僅驗收
- [x] **safety gate** — 危險指令規則先攔（pure rules, 0 LLM）
- [x] **clarify gate** — 模糊輸入反問，模糊/清楚自動分類
- [x] **3 向 routing** — answer / code / unclear（D14：棄信心閥值）
- [x] **真實驗收** — pytest subprocess，過=10 / 敗=2 / 逾時=0（D1）
- [x] **審計日誌** — decision_log 兩表，完整決策鏈可查
- [x] **executor registry** — 5 個內建 executor 自動注冊（claude-code / web-search / agnes-analyze/image/video）
- [x] **腦庫 SQLite+FTS5** — 跨 session 持久記憶，GBrain 雙寫
- [x] **記憶固化** — /brain/consolidate，gene/ 命名空間
- [x] **黑板** — .sdd/ 檔案系統，GET/POST /blackboard
- [x] **super-engine** — Playwright + Brave，Gemini daemon 2.3s
- [x] **MCP 搜尋** — DuckDuckGo HTML 解析，純 stdlib
- [x] **Agnes 多模態** — 看圖/產圖/產影片，4 API endpoints
- [x] **Skill Bridge** — 自動掛載 .claude/skills/ 為 executor
- [x] **協議模板庫** — 13 份 agent 交互模板（protocols/）
- [x] **Scheduler（自修復迴圈）** — Trigger 心跳 daemon + A 巡檢器 + task_queue + runner，系統會自己跑（Session C 完成）
- [x] **端到端測試** — test_e2e.py 覆蓋完整流程

---

## API 端點一覽

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/health` | 健康檢查 |
| POST | `/converse` | 閒聊路徑（blocking，帶歷史上下文） |
| POST | `/chat` | 任務路徑（safety → clarify → routing → exec） |
| POST | `/task/make` | 一次性 maker call（Scream 用） |
| POST | `/task/verify` | 單次驗收（check → pass/retry/escalate） |
| POST | `/task/run` | 同步執行（legacy，保持相容） |
| GET/POST | `/blackboard/{key}` | 黑板讀寫 |
| GET | `/executors` | 列出所有已注冊 executor |
| GET/POST | `/knowledge/{key}` | 腦庫讀寫 |
| GET | `/knowledge/search?q=` | FTS5 全文搜尋 |
| POST | `/brain/consolidate` | 記憶固化（experiences → gene/） |
| GET/POST | `/search` | DuckDuckGo 網頁搜尋 |
| POST | `/vision/analyze` | Agnes 看圖 |
| POST | `/image/generate` | Agnes 產圖 |
| POST | `/video/generate` | Agnes 產影片 |
| GET | `/video/status/{task_id}` | 輪詢影片狀態 |
| POST | `/skill-bridge/scan` | 掃描並注冊 Claude skills |
| POST | `/queue/push` | 手動把任務放入佇列（source A/B） |
| GET | `/queue/status` | 佇列五狀態計數 + 今日花費 |
| GET | `/queue/list` | 列出任務（可按 status 過濾） |
| GET | `/queue/task/{task_id}` | 單一任務詳情 |
| GET | `/cost` | 累計 execution_route 次數（審計） |
| GET | `/session/{session_id}` | 取得 session 狀態 |
| GET | `/settings` | 取得設定 |
| POST | `/settings` | 儲存設定 |
| GET | `/models` | 列出可用模型（free/paid 分層） |

---

## 下一棒（路線圖）

- ~~**Session C** — Scheduler（排程自動化）~~ ✅ 已完成：Trigger 心跳 daemon + B 佇列 API + A 巡檢器
- **Session B** — Model Router（成本控制：按任務類型 + 預算自動選模型）
- **Session D** — Auto-Consolidate（每次 verify 後自動萃取 gene 存 brain）

---

## 協作規則（給接手的 AI）

1. 架構與正確性決策由 Ryan 拍板，AI 執行不自行拍板，遇取捨先停下問。
2. 動手前先複述：這次做什麼、產出什麼、紅線在哪，等「繼續」再寫程式。
3. 不可逆動作（commit / push / 刪檔 / 改 .gitignore）一律先問。
4. 紅線檔案：勿擅改 `checker.py` / `decision_log.py` / `safety.py` / `clarify.py` 核心邏輯。
5. 輸出繁體中文。直言不諱，一步步思考，先給判斷再給細節。

完整願景、架構、路線圖 → [PROJECT.md](PROJECT.md)
決策記錄（為什麼這樣設計）→ [DECISIONS.md](DECISIONS.md)
Bug 修復記錄 → [BUGFIX.md](BUGFIX.md)

---

## 狀態

**v3 架構完整實作，340 tests 通過。**
Scream 主導計劃與執行、Claude CLI 專責驗收、AgentOS 純 Action 回圈層已上線。
Scheduler（自修復迴圈）已閉環：心跳 daemon 定期喚醒巡檢器 + runner，系統會自己跑。
