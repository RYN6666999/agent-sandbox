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

### 協作架構（與 `.scream-code/ARCHITECTURE.md` 對應）

```
Opus（董事 — 戰略判斷）
Scream Code（監督+規劃 — Foxconn PM）
Claude Code（執行 — 台積電產線）
AgentOS（辦公室 — NCC / 規章制度）← 你在這裡
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
┌──────────────────────────────────────────────────────┐
│               決策層 Router / Plan                    │
│  - 清晰度判定：動作 / 對象 / 可驗證完成判準            │
│  - direct / clarify / align 分流                      │
│  - align = 產出可派工的 Plan（此處放好模型）            │
└───────────────────────┬──────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────┐
│          協作層 Agent Loop (LangGraph 狀態機)          │
│  START → maker → checker → {pass / retry / escalate} │
│  （目前：Maker + Checker；未來：多 agent）              │
└──────┬─────────────────────────────┬─────────────────┘
       ↓                             ↓
┌──────────────┐            ┌────────────────────┐
│  MCP 工具層  │            │   腦庫 / 知識層     │
│（agent 的手腳）│           │（跨 session 的記憶） │
│ 搜尋/檔案/CLI/│           │ 專案脈絡/SOP/決策   │
│  外部 agent  │            │                    │
└──────┬───────┘            └─────────┬──────────┘
       ↓                             ↓
   [外部工具]                   [SQLite 知識庫]

── 全程旁掛 ──→ decision_log（審計：誰做了什麼決策、用了什麼工具）
```

### 層級關係（重要，不可配錯）
- **腦庫**是底層共用資源（記憶），所有 agent 透過統一介面讀寫，不直接碰資料庫。
- **MCP**是工具接入層（手腳），agent 透過它對外。
- **MCP 工具的調用必須經過 safety gate 與 audit log**，不可繞過。
- **審計日誌（記發生過什麼）** 與 **腦庫（記該知道什麼）** 是平行的兩個儲存層，不可混用。

---

## 三、技術節點 (Tech Stack & 接點)

| 節點 | 技術 | 角色 |
|------|------|------|
| 後端框架 | FastAPI | API 入口、端點 |
| 狀態機 | LangGraph | Maker/Checker 循環 |
| 模型接入 | LiteLLM / llm-router | 統一接多家模型、可切換 |
| 資料結構 | Pydantic | TaskSpec 等契約定義 |
| 儲存 | SQLite | 審計日誌 + 腦庫（MVP 階段不用 Postgres） |
| 工具接入 | MCP | agent 的 tool-calling 與外部工具 |
| 前端 | React (earth-tone UI) | 聊天 / 任務介面 |

### 禁用清單（MVP 階段）
Postgres、Redis、Docker、雲端服務（資料隱私 + 降複雜度）。

### 關鍵檔案地圖
- `orchestrator/decision_log.py` — 審計日誌（兩表：request_trace / routing_events）
- `orchestrator/checker.py` — Checker（真跑 pytest 的驗證器）
- `orchestrator/safety.py` — 危險指令規則攔截
- `orchestrator/clarify.py` — 模糊輸入反問閘門
- `orchestrator/maker.py` — Maker（執行層，settings["maker_model"] 覆蓋 mapping.py）
- `orchestrator/model_registry.py` — alias → LiteLLM kwargs（3 tier：alias / openrouter/ / raw）
- `align/core.py` — align 階段產出可派工 task brief
- `api/main.py` — /chat 與 /converse 端點；clarify_routing mode；forced_mode 支援
- `router/classifier.py` — routing_intent()：3向分類（answer/code/unclear）
- `router/` — 模型/技能路由
- `contracts/` — TaskSpec 規格定義
- `data/settings.json` — 執行期設定（plan_model / maker_model / checker_model / ...）
- `ui/src/store.ts` — 前端狀態機（Zustand）
- `ui/src/api.ts` — 前端 → 後端 HTTP contract

---

## 四、停止條件 (Loop 收斂判定)

Plan 階段必須固定以下三種停損，不可事後才補：
- **達標停**：Checker 分數 ≥ 7.0 → 交付。
- **煞車停**：超過 max_rounds，或連續兩輪進步 < 0.5 分（no_progress_streak）→ 停。
- **撞線停**：預算爆 / 環境錯 → escalate 交人。

---

## 五、目前進度 (Status — 接手前必讀)

已完成（git log 可查）：
- [x] **審計日誌** decision_log：兩表、event_type 區分 intent_gate / execution_route、
      單 request_id 查完整決策鏈、寫入失敗不阻斷主流程。
- [x] **Checker 真跑 pytest**：subprocess + timeout=60，過=10 / 敗=2 / 逾時=0，
      非程式碼任務才 fallback LLM 評分（標記 LLM_SCORED）。假綠燈已修復。
- [x] **clarify gate**：模糊/過短輸入先反問一句。
- [x] **safety gate**：規則攔截破壞性指令，只擋炸環境的、不擋業務刪除，已移到 clarify 之前。
- [x] **/converse 閒聊 vs /chat 任務分流**：按鈕區分，/converse 改同步阻塞回傳
      （修掉 WebSocket 競態條件）。
- [x] **routing 3 向分類**：answer / code / unclear，`unclear` 觸發 `clarify_routing` 問 A/B。
      棄信心閥值（推理模型不輸出低信心）（見 D14）。
- [x] **model settings 統一**：三個 agent 都從 settings.json 讀模型；
      maker dead field 修復（見 D15）；model_registry 三 tier resolve（見 D13）。
- [x] **測試覆蓋**：163 tests（158 pytest + 5 Vitest），涵蓋 API 流程、safety gate bypass 防護、
      store 狀態機。

待做（Backlog）：
- [ ] maker 換強力 coding 模型（D17，需 Ryan 拍板模型字串）。
- [ ] 用明確 brief 跑完整 Maker→Checker 循環，驗證核心假設（D9）。
- [ ] frontend clarify_routing UI（後端已完成，前端 A/B 問答尚未實作）。
- [ ] Agnes 多模態 MCP 接入（D18，roadmap 階段二）。

---

## 六、路線圖 (Roadmap)

### 階段一：核心細胞驗證（現在）
證明 Maker→Checker 兩 agent 循環能收斂並交付可用成果。
四個必須觀察的指標：Maker 真寫程式碼、Checker 真跑 pytest、失敗真實回退並修正、交付可用。

### 階段二：架構插槽落地
- 腦庫：接上真實 SQLite 儲存層 + 統一讀寫介面（`read_knowledge` / `write_knowledge`）。
- MCP：從寫死的工具升級為可註冊、可擴充的工具層；第一個接搜尋工具（解決 agent 不能聯網）。

### 階段三：多 agent 擴展
在 Maker/Checker 之外加入更多專長 agent（檢索、規劃、驗證…），
由 Plan 階段做真正的任務拆解與派工，routing_events 成為跨 agent 追錯的關鍵。

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
