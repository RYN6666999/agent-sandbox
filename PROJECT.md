# AgentOS — CLI 辦公室

> 本文件是專案的權威主文件。任何接手的人或 AI 請先完整讀完本文件，
> 再依「目前進度」與「路線圖」接上工作。架構與正確性決策由專案主持人 Ryan 拍板。

---

## 一、定調 (Positioning)

**AgentOS 沒有智力。它是 CLI 的辦公室。**

它不做決策、不寫程式、不推理。它只做四件事：

1. **安全門禁（safety gate）** — 危險指令先攔，規則優先，不交給模型判斷。
2. **審計（audit log）** — 每步分流、派工、驗收寫進 SQLite，全程可追溯。
3. **驗收設備（Checker）** — 真的開 subprocess 跑 pytest，不接受 LLM 幻覺綠燈。
4. **排程與協調（router / executor registry）** — 把任務分給對的 agent，排好誰先誰後。

就像一間辦公大樓：NCC 管法規、保全管門禁、總務排會議室、櫃檯接電話。
大樓自己不會寫程式、不會做決策 — 但它讓樓裡的每一間公司能專心做事。

### 四根支柱（不可妥協）

1. **真實驗收** — 能跑測試就用客觀結果（真跑 pytest），不能才用 LLM 評分。
2. **懂得停** — 系統必須知道何時該停（達標/煞車/撞線），不無限燒 token。
3. **危險紅線先擋** — 破壞執行環境的指令一律先攔，規則優先，不交給模型判斷。
4. **決策可追溯** — 每一步分流、派工、驗收都寫進審計日誌。

### 協作架構（v3 — 五角色）

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   Scream Code（計劃 + 執行）                              │
│   └─ 自己 call LLM、寫 code、判斷交付                     │
│                                                         │
│   Claude CLI（僅驗收）                                    │
│   └─ 不寫 code，只跑 pytest + 審查                        │
│                                                         │
│   AgentOS（純 Action 回圈層 — 基礎設施層，不參與智力判斷）         │
│   └─ safety gate / audit log / executor registry         │
│      / 腦庫 / 黑板 / 協議模板庫                            │
│                                                         │
│   Opus 4.8（GenSpark）— 顧問                              │
│   └─ 選用執行路徑，需要時才諮詢                            │
│                                                         │
│   Gemini（super-engine）— 小雜工（僅文字）                    │
│   └─ 摘要、分類、格式轉換等廉價任務，不能看圖                  │
│                                                         │
│   Agnes（api）— 多模態工具                                  │
│   └─ 看圖（agnes-2.0-flash）、產圖（agnes-image）、          │
│      產影片（agnes-video）、+ 便宜閒聊                      │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 一條判準

問：「這東西是讓 AgentOS 自己變強，還是讓接上來的 agent 或工具變強？」
若是前者，多半是越界搶執行層的活；若是後者，才是辦公室的本分。

因此：更強的 coding 模型、CLI 工具、搜尋引擎，都是被 AgentOS **調度與驗收的對象**，
不是 AgentOS 要去模仿或內化的東西。模型可換、工具可升級，
但辦公室職責（真驗收 / 會停 / 紅線 / 可追溯）不因換模型或換工具而動搖。

---

## 二、整體架構 (Architecture)

```
┌──────────────────────────────────────────────────────┐
│                   入口層 (API / UI)                   │
│  - /converse  閒聊路徑（同步回傳，帶最近 N 輪上下文）  │
│  - /chat      任務路徑                                │
│               ↓ safety gate（危險指令先攔，回 confirm_dangerous）│
│               ↓ clarify gate（模糊輸入先反問一句）     │
└───────────────────────┬──────────────────────────────┘
                        ↓
┌───────────────────────────────────────────────────────────┐
│               Scream 直接執行層（取代 LangGraph 狀態機）     │
│                                                           │
│  Scream 自己負責：                                          │
│  ├─ 理解任務、拆解步驟、call LLM（不限哪家模型）             │
│  ├─ 寫 code、改 code、跑測試                               │
│  ├─ 判斷何時該交付、何時該煞車                             │
│  └─ 需要時諮詢 Opus、派遣 Gemini 做廉價雜工                 │
│                                                           │
│  AgentOS 提供基礎設施（不參與決策）：                       │
│  ├─ safety gate（規則攔截，不給模型判斷）                   │
│  ├─ clarify gate（模糊輸入反問）                            │
│  ├─ audit log（記下發生過什麼）                             │
│  ├─ executor registry（三種 executor type）                 │
│  ├─ 腦庫（跨 session 記憶）                                │
│  ├─ 黑板（session 內共享狀態）                              │
│  └─ 協議模板庫（agent 交互提示詞模板）                      │
│                                                           │
└───────────────────────┬───────────────────────────────────┘
                        ↓
               ┌────────────────────┐
               │   外部工具 / 模型   │
               │  subprocess / MCP  │
               │  super-engine      │
               │  腦庫 SQLite       │
               └────────────────────┘

── 全程旁掛 ──→ decision_log（審計：誰做了什麼決策、用了什麼工具）
```

### 層級關係（重要，不可配錯）
- **Scream** 是執行主體，直接 call LLM、寫 code、判斷交付，不經 AgentOS maker proxy。
- **AgentOS** 是 Scream 下方的基礎設施層，提供安全、審計、調度能力，但不參與智力判斷。
- **Claude CLI** 是驗收角色，只在需要真實驗收時被 Scream 調用，不寫 code。
- **Opus 4.8** 是顧問，選用執行路徑，Scream 遇到架構難題時才諮詢。
- **Gemini（super-engine）** 是小雜工（僅文字），負責摘要、分類、格式轉換等廉價任務。
- **Agnes** 是多模態工具（看圖、產圖、產影片），補 Gemini 的文字-only 缺口。目前作為 converse 閒聊預設模型。其 image/video 系列已整合為 executor（agnes-image, agnes-video）。
- **腦庫**是底層共用資源（記憶），所有 agent 透過統一介面讀寫，不直接碰資料庫。
- **MCP**是工具接入層（手腳），agent 透過它對外。
- **MCP 工具的調用必須經過 safety gate 與 audit log**，不可繞過。
- **審計日誌（記發生過什麼）** 與 **腦庫（記該知道什麼）** 是平行的兩個儲存層，不可混用。

---

## 三、技術節點 (Tech Stack & 接點)

| 節點 | 技術 | 角色 |
|------|------|------|
| 後端框架 | FastAPI | API 入口、端點 |
| 模型接入 | LiteLLM / llm-router | 統一接多家模型、可切換 |
| 資料結構 | Pydantic | TaskSpec 等契約定義 |
| 儲存 | SQLite | 審計日誌 + 腦庫（MVP 階段不用 Postgres） |
| 工具接入 | MCP | agent 的 tool-calling 與外部工具 |
| 前端 | React (earth-tone UI) | 聊天 / 任務介面（已決定捨棄 TUI，以 API + shell client 為主） |
| Web LLM | super-engine (Playwright + Brave) | Gemini 免費版 / GenSpark(Opus) 兩條線路 |
| executor registry | orchestrator/executor_registry.py | register/get/list_all/run（支援 subprocess + super-engine + super-engine-warm）|
| super-engine daemon | super-engine/ask-daemon.ts | Keep-warm HTTP server，瀏覽器常駐，~2s 回應 Gemini |

### 角色對應

| 角色 | 技術對應 | 說明 |
|------|----------|------|
| Scream | `scream-code`（主 agent runtime） | 計劃 + 執行，自己 call LLM、寫 code |
| Claude CLI | `claude`（subprocess） | 僅驗收，跑 pytest + 審查，不寫 code |
| AgentOS | FastAPI + SQLite + executor registry | 基礎設施層，不參與智力判斷 |
| Opus 4.8 | GenSpark（super-engine line 1） | 顧問，選用執行路徑 |
| Gemini | super-engine daemon（line 2） | 小雜工，低延遲 2.3s |

### 禁用清單（MVP 階段）
Postgres、Redis、Docker、雲端服務（資料隱私 + 降複雜度）。

### 關鍵檔案地圖
- `orchestrator/decision_log.py` — 審計日誌（兩表：request_trace / routing_events）
- `orchestrator/checker.py` — Checker（真跑 pytest 的驗證器）
- `orchestrator/safety.py` — 危險指令規則攔截
- `orchestrator/clarify.py` — 模糊輸入反問閘門
- `orchestrator/maker.py` — Maker（執行層，settings["maker_model"] 覆蓋 mapping.py）
- `orchestrator/model_registry.py` — alias → LiteLLM kwargs（3 tier：alias / openrouter/ / raw）
- `orchestrator/executor_registry.py` — registry 核心（register/get/list/run，三種 type）
- `orchestrator/blackboard.py` — .sdd/ 檔案系統黑板
- `orchestrator/knowledge.py` — **腦庫 SQLite 儲存層**（write/read/search/get_knowledge，FTS5）
- `orchestrator/task_queue.py` — SQLite 佇列 + 狀態機（pending→running→passed/escalated/dead）+ `cost_ledger` 持久化油表
- `orchestrator/runner.py` — `run_loop()` 三停六分支；重啟後從 DB 重建油表
- `orchestrator/inspector.py` — A 巡檢器：跑本地 pytest，失敗去重後產任務入佇列（source="A"）
- `orchestrator/repair.py` — **真實自修復**：讀失敗測試 + 其 local-import source → LLM 出完整修正檔 → 寫回 repo → 跑真 repo pytest + 全套回歸守 → 失敗即 revert（紅線：不改測試、不出 repo、不留髒）。runner 對 source="A" 任務委派它。
- `orchestrator/heartbeat.py` — Trigger 心跳 daemon：`run_once()` / `run_forever()`，定期喚醒 inspector + runner
- `orchestrator/auto_consolidate.py` — Session D：verify verdict → 一條 gene/ experience，`/task/verify` 後 best-effort 寫 brain（pass→pattern / escalate→bug-fix，skip retry）
- `protocols/` — **協議模板庫**（13 份 agent 交互提示詞模板：handoff-opus / delegate-claude-code / delegate-subagent / record-session / review-request / task-breakdown / progress-report / write-protocol / agnes-multimodal / consolidate-experience / military-grade-sdlc / search-web / skill-bridge）
- `align/core.py` — align 階段產出可派工 task brief
- `api/main.py` — /chat / /converse / /task/{make,verify,run} / /blackboard / /executors / /knowledge / /queue/{push,status,list,task} / /cost / /search / /vision / /image / /video / /skill-bridge 端點
- `router/classifier.py` — routing_intent()：3向分類（answer/code/unclear）
- `router/` — 模型/技能路由
- `contracts/` — TaskSpec 規格定義（含 executor 欄位）
- `data/settings.json` — 執行期設定（含 executors 設定）
- `super-engine/ask-daemon.ts` — 🔥 Keep-warm HTTP daemon（port 3456，瀏覽器常駐）
- `super-engine/ask.ts` — One-shot CLI 模式（備用）
- `super-engine/config.js` — Provider 設定（genspark, gemini 兩條線路）
- `super-engine/setup-profile.ts` — Brave profile 一次性設定（指紋登入）
- `super-engine/brave-profile/` — 🔑 已登入的 Brave profile
- `scripts/agentos.sh` — Scream → AgentOS shell client（含 knowledge + protocol 指令）
- `scripts/login-genspark.sh` — GenSpark 登入 helper
- `tests/test_knowledge.py` — 腦庫 22 項測試（CRUD + FTS + metadata round-trip + slashes-in-key）

---

## 四、停止條件 (Loop 收斂判定)

Plan 階段必須固定以下三種停損，不可事後才補：
- **達標停**：Checker 分數 ≥ 7.0 → 交付。
- **煞車停**：超過 max_rounds，或連續兩輪進步 < 0.5 分（no_progress_streak）→ 停。
- **撞線停**：預算爆 / 環境錯 → escalate 交人。

---

## 五、目前進度 (Status — 接手前必讀)

已完成（git log 可查）：
- [x] **角色重構 v3** — Scream 直接執行（自己 call LLM、寫 code、判斷交付）、
      Claude CLI 僅驗收（跑 pytest + 審查）、
      AgentOS 為純 Action 回圈層（基礎設施層，不參與智力判斷）、
      Opus 4.8（GenSpark）為顧問（選用執行路徑）、
      Gemini（super-engine）為小雜工（摘要/分類/格式轉換）
- [x] **審計日誌** decision_log：兩表、event_type 區分 intent_gate / execution_route、
      單 request_id 查完整決策鏈、寫入失敗不阻斷主流程。
- [x] **Checker 真跑 pytest**：subprocess + timeout=60，過=10 / 敗=2 / 逾時=0，
      非程式碼任務 deleg Claude CLI 評分。移除了 LLM 評分 fallback（舊 _llm_check / _llm_score）。
- [x] **clarify gate**：模糊/過短輸入先反問一句。
- [x] **safety gate**：規則攔截破壞性指令，只擋炸環境的、不擋業務刪除，已移到 clarify 之前。
- [x] **/converse 閒聊 vs /chat 任務分流**：按鈕區分，/converse 改同步阻塞回傳
      （修掉 WebSocket 競態條件）。
- [x] **routing 3 向分類**：answer / code / unclear，`unclear` 觸發 `clarify_routing` 問 A/B。
      棄信心閥值（推理模型不輸出低信心）（見 D14）。
- [x] **model settings 統一**：三個 agent 都從 settings.json 讀模型；
      maker dead field 修復（見 D15）；model_registry 三 tier resolve（見 D13）。
- [x] **executor registry** — register/get/list/run 四介面，支援 subprocess / super-engine / super-engine-warm 三種 type
- [x] **Blackboard HTTP API** — GET/POST /blackboard 端點
- [x] **/task/run 同步端點** — safety gate → maker → blocking 結果
- [x] **scripts/agentos.sh** — shell client（run / blackboard / executors / health / knowledge / protocol）
- [x] **super-engine** — Playwright 驅動 Brave，兩條 provider 線路
      - GenSpark (Opus 4.8)：visible browser ~13-27s
      - Gemini 免費版：daemon warm 模式 **2.3s** 🔥
- [x] **keep-warm daemon** — ask-daemon.ts HTTP server（port 3456），瀏覽器常駐零啟動
- [x] **腦庫 SQLite 整合** — `orchestrator/knowledge.py`（write/read/search/get_knowledge），
      FTS5 全文搜尋，獨立 `data/knowledge.db`，HTTP 端點（POST/GET /knowledge），
      shell client 支援（knowledge-write / knowledge-read / knowledge-search），19 項測試全過
- [x] **協議模板庫** — `protocols/` 目錄，13 份 agent 交互提示詞模板（handoff-opus /
      delegate-claude-code / delegate-subagent / record-session / review-request /
      task-breakdown / progress-report / write-protocol / agnes-multimodal /
      consolidate-experience / military-grade-sdlc / search-web / skill-bridge），
      shell client 支援（protocol list / show / push），可推送到腦庫
- [x] **測試覆蓋**：pytest 全綠（CI 守），涵蓋 API、registry、super-engine、safety、blackboard、knowledge、queue、runner、inspector、heartbeat、auto-consolidate
- [x] **Phase 5 實戰驗證** — `/task/make` + GenSpark 13.5s 正常回應 ✅、
      `/task/verify` + pytest pass (10.0) / fail (2.0 + feedback) ✅、
      maker.py executor routing 修正 ✅
- [x] **Agnes 多模態 executors 接入** — agnes-image（agnes-image-2.1-flash）、
      agnes-video（agnes-video-v2.0）正式註冊為 executor
- [x] **MCP 搜尋工具接入** — `orchestrator/search.py`（DuckDuckGo HTML 解析器，純 stdlib）、
      `scripts/search-web.py`（CLI wrapper，註冊為 subprocess executor）、
      `POST/GET /search` API 端點、18 項測試全過
- [x] **Agnes 多模態 MCP 接入** — `orchestrator/agnes.py`（analyze_image / generate_image / generate_video）、
      `scripts/agnes-analyze/agnese-image/agnes-video.py`（CLI wrapper 各一）、
      `POST /vision/analyze, /image/generate, /video/generate + GET /video/status` API、
      20 項測試全過
- [x] **Skill Bridge — 自動掛載 Claude Skill** — `orchestrator/skill_bridge.py`（掃描 .claude/skills/）、
      從 210+ skill 中發現 17 個 executable、自動註冊 33 個 executor、
      `POST /skill-bridge/scan` API、9 項測試全過

### 已完成 Backlog（移至完成區）
- [x] 端到端整合測試（test_e2e.py 14 項全過）
- [x] MCP 搜尋工具接入（階段二）
- [x] Agnes 多模態 MCP 接入（階段二）
- [x] **全面 Debug 與測試債清理（2026-06-21）** — 共修復 16 個失敗測試（5 類問題）：
      executor registry 缺失自動注冊（D24）、測試 patch 已刪除的 `_llm_score`（D25）、
      `run_loop` → `run_verification` 改名未同步、`/models` 格式不一致、
      環境依賴測試加 `pytest.skip`。
      **結果：248 passed, 1 skipped（環境依賴）, 0 failed** ✅
      修復詳情見 [BUGFIX.md](BUGFIX.md)

### 已完成：Session C Scheduler（自修復迴圈閉環 ✅）
- ✅ `orchestrator/task_queue.py` — SQLite 佇列 + 狀態機（pending→running→passed/escalated/dead）+ `cost_ledger` 持久化油表
- ✅ `orchestrator/runner.py` — `run_loop()` 三停六分支（達標 ≥7.0 / 煞車 max_rounds+no_progress / 撞線 env_error+全局預算）；重啟後從 DB 重建油表
- ✅ `orchestrator/maker.py` — `make()` 回傳 `MakeResult`，抓 V4 Flash usage（$0.09/$0.18 per M），subprocess 路徑標記 `cost_known=False`
- ✅ `orchestrator/inspector.py` — A 巡檢器：跑本地 pytest，失敗去重（pending/running/escalated）後產任務入佇列（source="A"）
- ✅ B-side 手動佇列 API — `POST /queue/push`、`GET /queue/status`、`GET /queue/list`、`GET /queue/task/{id}`
- ✅ `orchestrator/heartbeat.py` — **Trigger 心跳 daemon（最後一棒）**：`run_forever()` 定期喚醒 inspector + runner，預檢油表跨日自動歸零。系統會自己跑了。
  - 啟動：`python -m orchestrator.heartbeat --interval 300`（`--once` 除錯）

### 已完成：Session D Auto-Consolidate（自我成長 ✅）
- ✅ `orchestrator/auto_consolidate.py` — `verdict_to_experience()`（純）+ `auto_consolidate()`（best-effort，never raises）
- ✅ `/task/verify` 通過/撞線後自動萃取 gene 存 brain，response 帶 `consolidated` keys；`settings.auto_consolidate` 預設 on，可關
- ✅ 只在 pass/escalate 觸發，skip retry（避免 brain 被中途態噪音污染）

### 下一棒
- Session B: Model Router（成本控制）— **評估後判定多半已落地**（`router/mapping.py` 按任務類型選模型 + `runner` 的 `cost_ledger`/撞線停）。剩「預算低時降級」一小片，且會傷 architecture 品質。擱置，真量到成本痛再補 ~20 行。詳見 `.scream-code/optimization-report-2026-06-22.md`。

### 擱置 Backlog
- frontend clarify_routing UI（React desktop 已廢棄，TUI 也不做）
- super-engine headless（GenSpark 封鎖 headless，繞過成本高）

---

## 六、路線圖 (Roadmap)

### 階段一：核心細胞驗證（已完成 ✅）
證明 **Scream 直接執行 → Claude CLI 驗收** 循環能收斂並交付可用成果。
Scream 自己寫 code、跑測試、判斷何時交付；Claude CLI 負責客觀驗收（真跑 pytest）。
三個必須觀察的指標已全部通過：Scream 能獨立完成任務（Phase 5 實戰驗證）、Claude CLI 真實驗收（pass/fail 正確判定）、失敗真實回退（score=2.0 + error feedback）。

### 階段二：架構插槽落地（已完成 ✅）
- 腦庫：接上真實 SQLite 儲存層 + 統一讀寫介面（`read_knowledge` / `write_knowledge`）。
- MCP 搜尋工具：DuckDuckGo HTML 解析器，純 stdlib，18 項測試 ✅
- Agnes 多模態 MCP：看圖/產圖/產影片，4 API endpoints，20 項測試 ✅
- Skill Bridge：自動掛載 Claude CLI 17 個 executable skill，9 項測試 ✅

### 階段三：多 agent 擴展
在 Scream + Claude CLI 之外加入更多專長角色（檢索、規劃、驗證…），
由 Scream 做真正的任務拆解與派工，routing_events 成為跨 agent 追錯的關鍵。

### 階段四：外部 agent / CLI 接入（願景的精彩處）
透過統一介面隔空調度外部 agent 與 CLI（如 Hermes、Claude Code 命令列模式），
讓 AgentOS 成為調度多家智能體的指揮中心。

### Backlog（記下但暫不做）
- README / 文件完善（本文件是第一步）
- 真沙箱隔離（目前 subprocess 跑在同機 temp dir，非真隔離，有安全債）
- `.sdd/` 大量 log JSON 進版控 → 評估丟 .gitignore
- 跨 session 持久記憶、隱藏任務偵測、Cherry Studio 借殼評估

---

## 七、協作規則（給接手的 AI）

1. 架構與正確性決策由 Ryan 拍板，AI 執行不自行拍板，遇取捨先停下問。
2. 動手前先複述：這次做什麼、產出什麼、紅線在哪，等「繼續」再寫程式。
3. 不可逆動作（commit / push / 刪檔 / 改 .gitignore）一律先問。
4. 紅線檔案：勿擅改 checker.py / decision_log.py / safety.py / clarify.py 核心邏輯。
5. 輸出繁體中文。直言不諱，一步步思考，先給判斷再給細節。