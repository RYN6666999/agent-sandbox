# AgentOS MCP — 真實流量驗證提示詞（Shadow Migration Plan）

> **用途**：MVP（`sandbox_execute`）落地後，把 Aris 舊 bridge 的 execute 階段導過來，用真實流量驗證整體設計。
> **給誰用**：直接餵給 Aris / Scream 或執行 agent（Cursor / Cline / Claude Code），照著跑。
> **前置條件**：`mcp_server/` MVP 已完成、`sandbox_execute` 驗收標準通過。
> **關聯文件**：`agentos-mcp-server-spec.md`（架構規劃書 v0.3）

---

## ⛔ 狀態：Phase 1 尚未真正完成，Phase 2 不可開始（2026-07-22）

現行 shadow 實作（`neuralis/scripts/agentos-aris-bridge.py`）與本計畫有結構性落差。
**照現況跑滿七天，會得到一份回答不了 Phase 3 決策問題的資料。**

### 量不到的硬 KPI

| 本計畫要求 | 現況 |
| --- | --- |
| 新舊結果差異 `diverged` < 2% | **量不到**。log 沒有 `old_result` / `new_result`，沒有比對邏輯 |
| Gate 誤擋率 / 漏擋率 | **量不到**。log 沒有 `gate_verdict` 欄位 |
| Checkpoint 磁碟壓力 | **量不到**。白名單全唯讀，`sandbox_execute` 不產生 checkpoint |
| Aris 呼叫節奏 QPS | 勉強可從 `queue_wait_ms` / `mcp_latency_ms` 推估 |

### 更根本的問題：現行 shadow 不是「影子」

本計畫 Phase 1 定義的 shadow 是「舊路徑照跑並回傳給 Aris，**同時**用同一個指令
打新路徑，比對兩邊結果」。

實際實作是：從 `task_desc` 剖出一個固定模板操作（`list_directory` / `read_file`
/ `get_cwd` 三選一）打一次 MCP，**不影子化舊路徑真正執行的指令，也不比對**。
這是合成探針（synthetic probe），不是影子模式。

而且新舊兩條路徑的能力集合已經不重疊：舊路徑執行任意指令，新路徑只有三個唯讀
操作。**大多數真實流量在新路徑上根本沒有對應動作可比。**

### 建議

要讓本計畫可執行，得先決定 shadow 的定位，二選一：

1. **縮小計畫**：承認新路徑只覆蓋唯讀操作，把 KPI 改成只衡量這三個操作的
   正確性與延遲。七天實測仍有價值，但推導不出 v0.2 的優先序（原本 §Phase 3
   的四類映射有三類要拿掉）。
2. **補齊比對層**：在 bridge 加真正的雙路徑記錄（`old_result` / `new_result`
   / `gate_verdict` / `diverged`），並接受「只有唯讀指令能比對」的先天限制。
   工作量遠大於 Phase 1 原本的估計。

**在拍板之前，Phase 2 的七天實測不要開始。**

### 已修復（不再是阻塞項）

- bridge payload 送出契約外的 `timeout` / `rollback_on_fail` → 已移除
- `path` 傳 `None` 導致型別驗證失敗 → 已 coerce 成 `""`
- 用 `returncode == 0` 判定成功（會把失敗記成 ok）→ 已改為解析 `isError`
- log rotation 把舊資料貼上今天的日期標籤 → 已改為用內容日期，且同日不切分

---

## 給執行 Agent 的角色說明

你正在協助把 `agentos-aris-bridge.py` 的 execute 階段從「直接呼叫 Scream 工具」遷移到「透過 MCP Server (port 8001) 呼叫 `sandbox_execute`」。這是一個**影子模式**（shadow mode）遷移 — 兩條路徑同時跑，比對結果，先觀察後切換，不做一步到位。

你的工作邊界：

- **允許**：修改 `agentos-aris-bridge.py`、新增 `mcp/observability/` 子模組、寫測試、產生度量報表
- **禁止**：修改 `mcp/sandbox/`、`mcp/gate/`、`api/`、`orchestrator/` 的既有邏輯（Level 1 結構安全）
- **決策權**：技術建議由你提，最終切換 / 回滾由使用者拍板；信心 <70% 的判斷須觸發「External Advisor」模式

回報格式一律走《決策分析》結構：Change / Benefits / Drawbacks / Risks / Costs / Alternatives / Verdict。

---

## 目標與非目標

### 目標

1. 讓 Aris 每天所有 execute 動作**同時**走舊路徑與新路徑（shadow mode）
2. 收集 **7 天真實流量**，取得四類實測資料：
   - Gate 誤擋率（false positive）
   - Gate 漏擋率（false negative）
   - Checkpoint 磁碟壓力（每日新增 tar.gz 總大小 / TTL 前累積峰值）
   - Aris 呼叫節奏（每分鐘 QPS 中位數 / p95 / 突發峰值）
3. 根據實測資料，**推翻或確認** 規劃書 §9 的 v0.2 / v0.3 / v0.4 順序

### 非目標

- **不做**功能擴充（不加 ontology / knowledge / loop 工具）
- **不做**性能調優（先量再優）
- **不做**舊 bridge 完整廢棄（本階段只做 shadow，不切主流量）

---

## 三階段執行計畫

### Phase 1：Shadow 接線（Day 0-1）

**做什麼**

1. 在 `agentos-aris-bridge.py` 的 execute 階段插入 shadow call：
   - 舊路徑照跑（回傳結果給 Aris）
   - **同時** async 呼叫 `sandbox_execute`，結果只寫 log、不回給 Aris
2. 新增 `mcp/observability/shadow_log.py`：
   - 寫入 `~/agent-sandbox/logs/shadow-YYYY-MM-DD.jsonl`
   - 每筆記錄：`{ts, command, old_result, new_result, gate_verdict, checkpoint_id, latency_ms_old, latency_ms_new, diverged: bool}`
3. 設定 kill switch：`AGENTOS_SHADOW=off` 環境變數可立即停 shadow call

> **實作現況（2026-07-22，與上方規劃不符）**
>
> | 規劃 | 實際 |
> | --- | --- |
> | `mcp/observability/shadow_log.py` | 不存在。shadow log 寫在 bridge 內（`_shadow_write_log`） |
> | `logs/shadow-YYYY-MM-DD.jsonl` | `logs/shadow.jsonl`，跨日 rotate 成 `.YYYYMMDD` 後綴 |
> | 上列 9 欄位 | 實際 8 欄且完全不同：`{ts, entry_id, route, op_name, shadow_status, queue_wait_ms, mcp_latency_ms, error_type}` |
> | `AGENTOS_SHADOW=off` | 實際是 `AGENTOS_SHADOW_ENABLED=0/1`（預設 0），另有 sentinel file `/tmp/agentos-shadow-kill` 作動態 kill switch |
> | 舊路徑照跑 + 同時打新路徑 | 沒有雙路徑。只用固定模板打一次 MCP |

**驗收**

- [ ] Aris 完全感受不到差異（舊路徑回應時間漂移 <5%）
- [ ] Shadow log 有寫入，欄位齊全 ← **未達成**，缺 `old_result` / `new_result` / `gate_verdict` / `diverged`
- [ ] `AGENTOS_SHADOW=off` 能即時關掉 shadow call，不需重啟 ← 變數名已改，sentinel file 機制可用

### Phase 2：資料收集（Day 1-8，實跑 7 天）

**做什麼**

1. 讓 Aris **照常工作**，不干預
2. 每天固定時間跑 `python scripts/shadow_report.py --date YYYY-MM-DD`，產出當日報表
3. 出現以下任一狀況立即停手回報：
   - Gate 誤擋率 >5%（可能規則過嚴）
   - Checkpoint 累積 >5GB（磁碟壓力異常）
   - Aris 呼叫 QPS p95 >20（比預期高一個量級）
   - Shadow log 寫入失敗（觀測層本身壞了）

**產出**

每日一份 `shadow-report-YYYY-MM-DD.md`，包含：

- 當日總呼叫數
- Gate verdict 分布（allow / deny / warn）
- Checkpoint 磁碟增量
- Latency 對比（old vs new，p50 / p95 / p99）
- Diverged 案例清單（新舊結果不同的指令，逐筆檢視）

### Phase 3：資料分析與堆疊決策（Day 8-9）

**做什麼**

1. 彙整 7 天資料為 `shadow-week1-analysis.md`
2. 依「四類實測資料」映射到 v0.2 優先級：

| 實測發現 | 對應下一步 |
|---|---|
| Aris 常做出「找不到工具」的錯誤決策（diverged 中 >20% 是工具路由問題） | 優先做 **Ontology**（路線 A） |
| Aris 常呼叫「查昨天做過什麼」類指令（>10% 呼叫是查詢 memory） | 優先做 **Knowledge Router**（路線 B） |
| Gate 誤擋率高（>3%）或漏擋（任一件） | 優先做 **Gate v2**（規則精修，非 v0.2 內容但必須插隊） |
| Checkpoint 每日 >2GB 且無業務理由 | 優先做 **Sandbox 優化**（差分 checkpoint，非 v0.2 內容但必須插隊） |
| 都很正常，沒明顯痛點 | 按規劃書 §9 順序走 v0.2 |

3. 產出 `agentos-mcp-server-spec.md` 的 §10 補充章節：「MVP 後堆疊路線」（依實測決定，非依規劃想像）

---

## 驗證指標（KPIs）

### 硬指標（過不了直接回滾 shadow）

| 指標 | 門檻 | 測量方式 |
|---|---|---|
| Aris 舊路徑延遲漂移 | <5% | 比對 shadow 開啟前後一週的 `agentos-aris-bridge` 平均回應時間 |
| Shadow log 寫入成功率 | ≥99.5% | 每筆呼叫都應該有對應 log 條目 |
| 舊路徑 / 新路徑結果差異 | <2% | `diverged: true` 的比例 |
| `AGENTOS_SHADOW=off` 生效時間 | <10 秒 | 從設環境變數到下一次呼叫實際跳過 shadow |

### 觀察指標（不設門檻，用來決定 v0.2 順序）

| 指標 | 用途 |
|---|---|
| Gate verdict 分布（allow / deny / warn） | Gate 規則校準 |
| Checkpoint 每日新增 tar.gz 大小 | Sandbox 磁碟壓力 |
| Checkpoint TTL 前累積峰值 | Sandbox 清理策略調整 |
| Aris 呼叫 QPS 中位數 / p95 | 是否需要 async / batch |
| 呼叫類型分布（exec / query / memory 語意分類） | 決定 v0.2 優先做哪類工具 |
| Latency old vs new p50 / p95 / p99 | MCP 層 overhead 是否可接受 |

### 軟指標（人工判斷）

| 指標 | 判斷方式 |
|---|---|
| Aris 開發體驗變化 | 使用者主觀回饋，每 3 天問一次「有感覺變慢或變怪嗎？」 |
| Diverged 案例是否有共通模式 | 人工翻閱 diverged log，找出可歸類的模式 |
| 是否出現「規劃時沒想到的痛點」 | 使用者遇到任何 friction 都記到 `shadow-week1-notes.md` |

---

## 風險與回滾預案

| 風險 | 觸發條件 | 回滾動作 |
|---|---|---|
| Shadow 拖慢舊路徑 | 舊路徑延遲漂移 >5% | 立即 `AGENTOS_SHADOW=off`；檢視 async 實作是否誤成 blocking |
| Gate 誤擋災難 | 單日誤擋 >10 件 | 先切 `mode=warn` 只記錄不擋；規則精修後再切回 |
| Checkpoint 灌爆磁碟 | 磁碟使用率 >85% | 立即縮短 TTL 到 6h；找出佔用最大的 session 手動清理 |
| MCP Server 掛掉 | port 8001 無回應 | Shadow call 應 fail silently，不影響舊路徑；重啟 MCP Server |
| Aris 感受到差異 | 使用者主觀回報變慢 | 立即 `AGENTOS_SHADOW=off`；查 shadow 是否誤成 blocking |

**Kill switch 三層**：

1. 環境變數 `AGENTOS_SHADOW=off`（最快，10 秒內生效）
2. `agentos.sh mcp stop`（停整個 MCP Server，shadow 自然失效）
3. Git revert bridge 的 shadow 接線 commit（最徹底）

---

## 檢核清單（Executor Checklist）

### 開工前

- [ ] MVP 驗收 3 條全通過
- [ ] `~/agent-sandbox/logs/` 目錄存在且可寫
- [ ] 磁碟剩餘空間 >20GB
- [ ] 舊 bridge 的 execute 階段有明確的 hook 點可插入 shadow call
- [ ] 已對 `agentos-aris-bridge.py` 開分支 `feature/shadow-migration-week1`

### Phase 1 收工前

- [ ] Shadow log 樣本檢視過至少 20 筆，欄位正確
- [ ] `AGENTOS_SHADOW=off` 手動測試過關閉功能
- [ ] 舊路徑延遲對比：shadow 開啟前後至少各 1 小時樣本
- [ ] 有回滾 commit 準備好可即時 revert

### Phase 2 每日

- [ ] 早上執行 `shadow_report.py` 產出前一日報表
- [ ] 檢查四個「立即停手」條件是否觸發
- [ ] 把當日發現記到 `shadow-week1-notes.md`

### Phase 3 收工

- [ ] 產出 `shadow-week1-analysis.md`
- [ ] 對照四類實測資料 → 決定 v0.2 順序
- [ ] 寫入規劃書 §10「MVP 後堆疊路線」
- [ ] 使用者拍板下一步方向後才動 v0.2

---

## 給使用者的決策點

**Day 1 結束後**：檢視 Phase 1 驗收 4 條，決定要不要進 Phase 2
**Day 4**：中期健檢，可提前終止
**Day 8**：Phase 2 結束，看 Phase 3 分析報告後決定 v0.2 方向

**不要在 Day 8 之前排 v0.2 v0.3 v0.4** — 這是這份計畫的核心紀律。用實測資料當對抗性測試（Adversarial 原則），不用規劃想像決定順序。

---

## 附錄：Shadow Log 範例格式

```jsonl
{"ts":"2026-07-22T08:30:12.345Z","session_id":"aris-001","command":"ls /tmp","old_result":{"status":"ok","stdout":"..."},"new_result":{"status":"ok","stdout":"...","checkpoint_id":"ckpt-abc"},"gate_verdict":"allow","latency_ms_old":45,"latency_ms_new":78,"diverged":false}
{"ts":"2026-07-22T08:31:05.123Z","session_id":"aris-001","command":"rm important.log","old_result":{"status":"ok"},"new_result":{"status":"rolled-back","checkpoint_id":"ckpt-def","rollback_applied":true},"gate_verdict":"allow","latency_ms_old":32,"latency_ms_new":156,"diverged":true,"divergence_note":"new path rolled back on non-zero exit"}
```

---

## 版本

- 2026-07-21 v0.1 初稿：shadow migration + 7 天實跑計畫 + KPIs + 回滾預案
- 2026-07-22 v0.2：文件移入 `docs/` 納版控。加註 Phase 1 未完成、Phase 2 不可開始的
  結論與理由（四項硬 KPI 有三項量不到、現行 shadow 是合成探針非影子模式）。
  標註 Phase 1 各項的實作現況落差。列出已修復的四個 bridge 缺陷。
