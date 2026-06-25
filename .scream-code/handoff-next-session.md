# AgentOS — 接續提示詞（Session 接力）

> 本文件記錄前一 session 的完成事項與當前狀態，
> 讓接手的新 session 可以直接接上，不用重讀整個專案。
>
> **接手第一件事：讀 [core-goal.md](core-goal.md) — 這是永久核心目標，
> 定義了所有行動的最高指導原則和決策框架。**

---

## 專案定位

**AgentOS** 是一個多角色產線作業系統，定位是「CLI 辦公室」——不做智力判斷，只做四件事：
安全門禁（safety gate）、審計（audit log）、驗收設備（Checker）、排程協調（executor registry）。

架構版本：**v3** — Scream Code 直接執行，AgentOS 純基礎設施層。

### 五角色

| 角色 | 職責 | 技術 |
|------|------|------|
| **Scream Code** | 計劃 + 執行（call LLM、寫 code、判斷交付） | scream-code runtime |
| **Claude CLI** | 僅驗收（跑 pytest + 審查，不寫 code） | subprocess |
| **AgentOS** | 基礎設施（safety gate / audit log / executor registry / 腦庫） | FastAPI + SQLite |
| **Opus 4.8** | 顧問，選用執行路徑 | GenSpark 網頁版 |
| **Gemini** | 小雜工（摘要、分類、格式轉換） | super-engine daemon |
| **Agnes** | 多模態工具（看圖、產圖、產影片） | Agnes API |

---

## 前 session 完成事項（commit log）

```
5bb0b66 fix: knowledge POST key 改 path-based URL — 與 GET /knowledge/{key} 一致
6c21b3a feat: 記憶固化 Phase 1-3 — consolidate protocol + /brain/consolidate 端點 + 測試
e41dda0 test: 新增端到端整合測試 — /task/make + /task/verify 9 項
9002a33 docs: 同步 PROJECT.md + task_plan.md — 階段一完成、移除 TUI、重排優先序
7291d54 sync: 對齊線上線下 — 新增 task_plan.md + military-skill-improvement.md
a19b6a8 feat: MCP 搜尋工具接入 + military-grade SDLC 協議
57fb6e9 feat: Agnes 多模態 MCP 接入（P3）— 看圖/產圖/產影片
b930d35 feat: Skill Bridge — 自動掛載 Claude CLI 17 個 executable skill
```

### 詳細成果

1. ✅ **MCP 搜尋工具接入（P2）**
   - `orchestrator/search.py` — DuckDuckGo HTML 搜尋模組，純 Python stdlib（urllib + html.parser），無外部依賴
   - `scripts/search-web.py` — CLI wrapper，註冊為 executor registry 的 subprocess 型 executor
   - `data/settings.json` — 註冊 web-search executor
   - `api/main.py` — 新增 `POST /search` + `GET /search?q=` 端點，回傳結構化結果（title/url/snippet）
   - `tests/test_search.py` — 18 項測試全過（parser 解析、mock HTTP、API 端點、CLI wrapper）
   - 遵循現有 executor registry pattern（與 claude-code / web-llm-genspark 一致）

2. ✅ **Agnes 多模態 MCP（P3）**
   - `orchestrator/agnes.py` — analyze_image / generate_image / generate_video / get_video_status
   - `scripts/agnes-analyze.py / agnes-image.py / agnes-video.py` — CLI wrapper 各一
   - `api/main.py` — POST /vision/analyze, /image/generate, /video/generate + GET /video/status/{id}
   - `protocols/agnes-multimodal.md` — 多模態協議
   - `tests/test_agnes.py` — 20 項測試全過
   - 看圖支援 URL + base64，產影片非同步 polling

3. ✅ **Skill Bridge（Session A）**
   - `orchestrator/skill_bridge.py` — 掃描 .claude/skills/，從 210+ skill 發現 17 個 executable，註冊 33 個 executor
   - `api/main.py` — POST /skill-bridge/scan 端點
   - `protocols/skill-bridge.md` — 協議
   - `tests/test_skill_bridge.py` — 9 項測試全過
   - notebooklm 透過 run.py + --question flag 確保 venv 正確
   - military-grade-workflow 等 .sh/.py 腳本自動掛載

---

## 當前狀態

### 已完成的功能

- executor registry（register/get/list/run，三種 type）
- super-engine（Playwright + Brave，GenSpark 13-27s / Gemini 2.3s）
- 腦庫 SQLite+FTS5（22 項測試）
- 協議模板庫（13 份協議）
- Checker 真跑 pytest
- safety gate / clarify gate
- Phase 5 實戰驗證通過
- Agnes image/video executors
- 記憶固化機制
- MCP 搜尋工具（web-search executor + /search API + 18 項測試）
- Agnes 多模態 MCP（agnes-analyze / agnes-image / agnes-video executors + 4 API endpoints + 20 項測試）
- Skill Bridge（自動掛載 Claude CLI 17 個 executable skill → 33 個 executor + 掃描 API + 9 項測試）
- **Session C Scheduler（自修復迴圈閉環）** — task_queue + runner（三停六分支）+ inspector（A 巡檢器）+ B 佇列 API（/queue/*）+ Trigger 心跳 daemon（heartbeat.py）。系統會自己跑了。
- **Session D Auto-Consolidate（自我成長）** — auto_consolidate.py：/task/verify 通過/撞線後自動萃取 gene 存 brain。系統會自己記了。
- **全測試通過：pytest 全綠（CI 自動守）**

### 待辦（依優先序）

```
已完成:
  P0: 端到端測試 ✅
  P1: 記憶固化 ✅
  P2: MCP 搜尋工具 ✅
  P3: Agnes 多模態 MCP ✅
  Session A: Skill Bridge ✅
  ──────────── Roadmap 階段二完成 🎉
  Session C: Scheduler（排程自動化）✅ — 自修復迴圈閉環
  Session D: Auto-Consolidate（自我成長）✅ — verify 後自動寫 gene
  ──────────── Session C + D 完成 🎉

下一個:
  無硬性 — 跑起來看真實使用再定
  Session B（Model Router）擱置：多半已由 mapping.py + cost_ledger 覆蓋

Backlog: clarify_routing UI / headless / 沙箱 / Model Router
```

### 已決定不做

- AgentOS TUI（terminal UI）— 以 API + shell client 為主
- GASP skill 研究（TUI 取消後不再需要）

---

## 給接手的 Scream Code：下一步動作

### 已完成：Session C — Scheduler（排程自動化）✅

自修復迴圈已閉環，系統會自己跑：
- `orchestrator/task_queue.py` — SQLite 佇列 + 狀態機 + cost_ledger 持久化油表
- `orchestrator/runner.py` — `run_loop()` 三停六分支
- `orchestrator/inspector.py` — A 巡檢器：跑本地 pytest，失敗去重後產任務入佇列
- `orchestrator/heartbeat.py` — Trigger 心跳 daemon（`python -m orchestrator.heartbeat`）
- B 佇列 API：`/queue/push`、`/queue/status`、`/queue/list`、`/queue/task/{id}`

### 已完成：Session D — Auto-Consolidate（自我成長）✅

系統會自己記了：
- `orchestrator/auto_consolidate.py` — `verdict_to_experience()`（純）+ `auto_consolidate()`（best-effort）
- `/task/verify` 通過/撞線後自動萃取 gene 存 brain，response 帶 `consolidated` keys
- 只在 pass/escalate 觸發（skip retry），`settings.auto_consolidate` 預設 on 可關

### 下一個任務：請參考 core-goal.md 的決策框架自主決定

核心循環 + 自修復 + 自我成長 + 記憶四維皆已閉環。
目前狀態：（跑 pytest 看即時數）

### 本輪完整成果（2026-06-24 ~ 06-25）

**Core Goal 系統** ✅
- core-goal.md 永久目標定義 + CreateGoal durable + Cron 0 8 * * *
- 行為協議：完成後自動分析下一步，不等指令

**記憶四維全修** ✅
- 調用：Maker/Reflect 接入腦庫；Repair 查 brain 命中→record_access
- 成長：Dedup 206→30→20 條；內容增強（✅/❌ + domain 偵測）
- 連結：related_ids schema + update_knowledge + link_entries
- 迭代：age+confidence prune；confidence 動態分級；heartbeat 定期 prune+eval

自主運作已設定：
- `core-goal.md` — 永久核心目標（高於本文件）
- `CreateGoal` 已註冊 — durable goal 跨 session 持續
- Cron `0 8 * * *` — 每日 8:00 CST 自動喚醒開始自主工作
- 行為規則：完成任務後自動分析下一步並繼續（不等指令）

### 紅線提醒

- 不可擅改 `checker.py` / `decision_log.py` / `safety.py` / `clarify.py` 核心邏輯（PROJECT.md 規則 4）
- git mutations（commit/push/刪檔）要先問
- 輸出繁體中文

### 關鍵檔案地圖

| 檔案 | 說明 |
|------|------|
| `api/main.py` | API 端點（/task/make、/task/verify、/brain/consolidate、/knowledge 等） |
| `orchestrator/executor_registry.py` | Executor 註冊與執行核心 |
| `orchestrator/knowledge.py` | 腦庫儲存層（含 consolidate_experiences） |
| `orchestrator/model_registry.py` | 模型 alias 映射 |
| `data/settings.json` | 執行期設定（含 executors 定義） |
| `protocols/` | 13 份協議模板 |
| `orchestrator/task_queue.py` | SQLite 佇列 + 狀態機 + cost_ledger 油表 |
| `orchestrator/runner.py` | `run_loop()` 三停六分支 |
| `orchestrator/inspector.py` | A 巡檢器（跑 pytest，失敗去重產任務） |
| `orchestrator/heartbeat.py` | Trigger 心跳 daemon（喚醒 inspector + runner） |
| `tests/test_e2e.py` | 端到端測試（mock pattern 參考） |
| `orchestrator/search.py` | 網頁搜尋核心模組（DuckDuckGo HTML 解析器，純 stdlib） |
| `scripts/search-web.py` | 搜尋 CLI wrapper（executor registry subprocess 用） |
| `tests/test_search.py` | 搜尋 18 項測試 |
| `orchestrator/agnes.py` | Agnes 多模態核心（analyze_image / generate_image / generate_video） |
| `orchestrator/skill_bridge.py` | Skill Bridge 掃描器（自動掛載 Claude skill → executor） |
| `scripts/agnes-analyze.py` / `agnes-image.py` / `agnes-video.py` | Agnes CLI wrapper |
| `protocols/search-web.md` | 搜尋協議 |
| `protocols/agnes-multimodal.md` | 多模態協議 |
| `protocols/military-grade-sdlc.md` | 軍規開發工作流協議 |
| `protocols/skill-bridge.md` | Skill Bridge 協議 |
| `tests/test_search.py` | 搜尋 18 項測試 |
| `tests/test_agnes.py` | Agnes 20 項測試 |
| `tests/test_skill_bridge.py` | Skill Bridge 9 項測試 |
| `.scream-code/prompt-to-opus-review.md` | 給 Opus 的審查提示詞 |

### 腦庫已寫入的參考資料

```
protocol/opus-review-2026-06-20 — AgentOS 審查請求（給 Opus 的完整提示詞）
gene/infrastructure/... — 前 session 固化的經驗
```

可透過 API 讀取：
```bash
curl http://localhost:8000/knowledge/protocol/
curl http://localhost:8000/knowledge/gene/infrastructure/
```

---

## 啟動命令

```bash
cd ~/agent-sandbox
source .venv/bin/activate

# 確認 API server 有在跑
curl http://localhost:8000/health

# 確認 super-engine daemon 有在跑
curl http://127.0.0.1:3456/health

# 跑測試
python -m pytest tests/ -v --tb=short
```