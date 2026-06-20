# 提示詞：Opus 審查 AgentOS 專案進度

> 透過 GenSpark（super-engine）送達 Opus 4.8
> 協議：`review-request.md` + `handoff-opus.md`

---

## 專案背景

你正在審查的專案是 **AgentOS** — 一個多角色產線作業系統，定位是「CLI 辦公室」，不做智力判斷，只做四件事：安全門禁、審計、驗收設備、排程協調。

架構版本：**v3**（Scream 直接執行，AgentOS 純基礎設施層，Opus 回歸顧問角色）

### v3 五角色

| 角色 | 職責 | 技術 |
|------|------|------|
| **Scream Code** | 計劃 + 執行（call LLM、寫 code、判斷交付） | scream-code runtime |
| **Claude CLI** | 僅驗收（跑 pytest + 審查，不寫 code） | subprocess |
| **AgentOS** | 基礎設施（safety gate / audit log / executor registry / 腦庫 / 黑板） | FastAPI + SQLite |
| **Opus 4.8（你）** | 顧問，選用執行路徑 | GenSpark 網頁版 |
| **Gemini** | 小雜工（摘要、分類、格式轉換） | super-engine daemon |
| **Agnes** | 多模態工具（看圖、產圖、產影片） | Agnes API |

---

## 目前的專案狀態

### 已完成

1. **executor registry** — register/get/list/run 四介面，三種 type（subprocess / super-engine / super-engine-warm）
2. **super-engine** — Playwright 驅動 Brave，GenSpark 13-27s + Gemini daemon 2.3s
3. **腦庫 SQLite+FTS5** — 19 項測試全過，跨 session 持久記憶
4. **協議模板庫** — 9 份 agent 交互提示詞（含新加的 consolidate-experience）
5. **Checker 真跑 pytest** — subprocess timeout=60，過=10 / 敗=2 / 逾時=0
6. **safety gate** — 規則攔截（rm -rf、DROP TABLE…），不交給模型判斷
7. **Phase 5 實戰驗證** — `/task/make` + GenSpark ✅、`/task/verify` pass/fail ✅
8. **Agnes image/video executors 接入** — agnes-image / agnes-video 正式註冊
9. **記憶固化** — consolidate protocol + `/brain/consolidate` 端點 + 基因格式定義
10. **端到端測試** — 14 項測試，mock 模式全過

### 待辦（依優先序）

1. MCP 搜尋工具接入（讓 agent 能聯網）
2. Agnes 多模態 MCP 接入
3. super-engine headless 模式（GenSpark 封鎖 headless，繞過成本高）

### 已決定不做

- AgentOS TUI（terminal UI）— 以 API + shell client 為主
- GASP skill 研究（TUI 取消後不再需要）

---

## 請你審查的重點

### 1. 架構健全性

- v3 角色分工（Scream 執行、AgentOS 基礎設施、Opus 顧問）是否合理？
- 四根支柱（真驗收、懂得停、紅線先擋、決策可追溯）是否有缺口？
- executor registry 三種 type 是否夠用？是否需要第四種？

### 2. 記憶固化設計

我剛實作了記憶固化機制：
- Phase 1：手動 consolidation protocol
- Phase 2：基因格式（`gene/<domain>/<slug>`，含 metadata）
- Phase 3：`POST /brain/consolidate` 端點

你覺得：
- 基因格式夠完整嗎？該加什麼欄位？
- 跨 session 的基因如何自動組合？
- 如何判斷哪些經驗值得固化？

### 3. 決策回顧

以下是本專案的關鍵決策，請逐一評論是否正確：

**D1：Checker 必須真跑 pytest，不接受 LLM 評分** ✅
**D3：危險指令用規則攔，不交給模型** ✅
**D11：三向分類（answer/code/unclear）取代信心閥值** ✅
**D19：executor registry 取代硬編碼 subprocess spawn** ✅
**D22：TUI 方向取消，以 API + shell client 為主** ❓
**D23：v3 角色重新定位，Scream 直接執行** ✅

### 4. 風險提醒

- 目前無真沙箱隔離（subprocess 跑同機 temp dir）
- MVP 禁用 Docker/Postgres/Redis/雲端
- MCP 工具調用須經 safety gate + audit log，但尚未全面落實
- Agnes image/video executor 無測試覆蓋

### 5. 路線圖建議

目前的優先序：
```
P0: MCP 搜尋工具（讓 agent 能聯網）
P1: Agnes 多模態 MCP
P2: super-engine headless
Backlog: 沙箱隔離 / clarify_routing UI
```

你覺得這個順序對嗎？有哪個風險該提前處理？

---

## 交付格式

請輸出以下結構：

```json
{
  "verdict": "overall | minor-concern | major-concern",
  "score": 1-10,
  "architecture_review": {
    "strengths": ["..."],
    "weaknesses": ["..."],
    "recommendations": ["..."]
  },
  "memory_consolidation_review": {
    "score": 1-10,
    "feedback": "..."
  },
  "decision_review": {
    "correct_decisions": ["D1", "..."],
    "questionable_decisions": ["D22: ..."],
    "missed_decisions": ["..."]
  },
  "risk_assessment": {
    "critical": ["..."],
    "watch": ["..."]
  },
  "roadmap_advice": "...."
}
```

---

## 交付管道

審查結果請寫入 gbrain（strategic_direction），Scream 下次讀取後會：
1. 評估你的建議
2. 更新 DECISIONS.md（如有必要）
3. 固化你提出的關鍵 insight 到腦庫
