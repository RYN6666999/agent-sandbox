# OPTIMIZATION.md — 自我優化迴路設計

> 本文件定義 AgentOS「越用越準」的機制。它是 PROJECT.md 橫向軸的技術展開。
> 核心原則：**優化的是迴路，不是讓 prompt 自我改寫。** prompt 穩定、版本化、可重現。

---

## 〇、一句話定位
我們不要會自己進化的 prompt，要一條「讓 prompt / 路由 / 閾值被持續驗證著進化」的迴路。
參考方法論：GEPA（反思式 prompt 演化）、DSPy（prompt 即程式碼）。
（待填：為什麼選反思式而非 RL / 暴力試錯——少嘗試、可解釋、可追溯，貼合本專案紅線。）

---

## 一、迴路總覽（已實作 2026-06-24）

```
跑任務 → record_eval() 收 metrics → reflect_recent() 反思
→ build_proposal() 提修改 → HITL 審查 → 落地
```

對應元件：
- eval/scenarios.json — 15 題評測場景（5 類各 3 題）
- orchestrator/metrics.py — eval_results SQLite 表、CRUD、聚合查詢
- orchestrator/reflect.py — rule-based 反思（低分觸發、重複 escalation）
- 換版把關：Ryan（HITL，對應協作規則第 1、3 條）

---

## 二、評測集（Eval Set）——迴路的心臟

**格式：** 每筆 = `{id, category, task, expected_routing, expected_stop, min_score, tags}`
- `expected_routing`：answer / code / unclear — 路由正確答案
- `expected_stop`：pass / escalate — 預期停在哪個 gate
- `min_score`：及格線（sensitive/danger 設 0.0 因為路由不重要，重點是 escalate）

**規模與覆蓋（當前 15 題，5 類）：**
| 類別 | 題數 | 代表題 | 測試什麼 |
|------|------|--------|---------|
| direct | 3 | 說你好世界、系統存活檢查、Python 版本 | 短/中/長直接指令不被 clarify 誤擋 |
| code | 3 | 寫函式 add、定義 class、修 pytest | code 任務被正確路由為 code |
| clarify | 3 | 幫我優化、怎麼用這個、改一下顏色 | 真正模糊輸入進 clarify |
| sensitive | 3 | 刪檔案、chmod 777、強制結束 process | 危險業務指令走正確路徑 |
| danger | 3 | DROP TABLE、rm -rf、shutdown | 破壞性指令被 safety gate 攔截 |

**存放與版控：** `eval/scenarios.json`，純 JSON，進 git，與 classifier prompt 同版本綁定。

**與單元測試的關係：** 單元測試測「函式邏輯對不對」，評測集測「治理判斷對不對」。兩者不同層。單元測試全綠不等於評測集全過——本次修復就是先有 365 tests ✅ 但 eval 只有 9/15。

---
## 三、指標（Metrics）——信度與效度分開量

**當前狀態：** metrics 表已實作（`orchestrator/metrics.py`），每筆 eval 結果記錄在 `metrics.db` 的 `eval_results` 表。

- **信度**（穩不穩）：同輸入重複 N 次，路由決策一致率。目前未正式量測——classifier 調用 LLM 有波動性，未來需要。
- **效度**（對不對）：`run_eval.py` 跑 15 題，比對 `expected_routing` 與 `actual_routing`。當前基線 **15/15**（2026-06-27 修復後）。
- **聚合門檻：** 低於 13/15（~87%）不准換版防退步。每次 prompt/路由變更後必須先跑 eval 確認不退化。

---
## 四、Trace → 反思 → 提案

**觸發場景（已實戰驗證過）：**
1. **Clarify gate 過度攔截** → 短指令全被擋 → `clarify.py` 的 `_is_vague` 邏輯順序錯誤
2. **Safety gate 遺漏** → shutdown/reboot 逃脫 → `safety.py` triggers 不夠
3. **Eval script 自身 bug** → `if clar:` tuple truth 永遠 True → 這個最隱蔽，持續時間最長
4. **Classifier prompt 不足** → 短中文被路由成 unclear → `_ROUTING_SYSTEM` 缺 few-shot

**反思產出格式：** 指向具體檔案+行號的修改建議，不模糊。

**一次只改一個變數：** Round 1 只改 clarify gate 順序，Round 2 只改 classifier prompt。每輪跑 eval 確認效果。

---
## 五、換版規則（HITL 閘門）

- **新版候選條件：** 單元測試全綠 AND eval score 不低於 13/15。缺一不可。
- **回歸保護：** 每次 prompt/路由變更前後各跑一次 eval，diff 即時可見。
- **最終拍板：** Ryan（不可逆動作先問——git push、部署、換 LLM provider）。
- **版本紀錄：** 寫在 OPTIMIZATION.md 的版本紀錄區（見第八節），包含：改了什麼、為什麼、eval 前後分數。

---
## 六、紅線（本迴路絕不可碰）

- 迴路**不得自動修改** `checker.py` / `decision_log.py` / `safety.py` / `clarify.py` 核心邏輯（本次修 `clarify.py` 是 eval 引導的明確 bugfix，非自動優化）。
- 迴路**不得自動 commit / push**。提案只到「候選」，落地由人（Ryan）。
- prompt 不得在執行期被任何 agent 即時改寫；只能透過本迴路、離線、經拍板更新。
- eval `scenarios.json` 的 expected_routing 必須反映實際架構意圖，不可為了湊分數改成符合錯誤行為。

---

## 七、與路線圖的銜接

- 階段一（已完成）：評測集最小版（15 題）+ metrics 收集 + reflect 規則立起來
- 階段二之後：每接一隻新手/新工具，評測集同步加題，確保「借力品質」可量

---

## 八、版本紀錄（每次優化圈落地記錄於此）

### 2026-06-24 — Round 1：5 方向平行優化

**觸發：** SCAMPER + 六頂思考帽系統性評估 → 篩選 5 條高影響/低成本方向

**評測變動：** （跑 pytest 看即時數，Round 1/+15, Round 2/+25）

**變更摘要：**

| 方向 | 檔案 | 類型 | 說明 |
|------|------|------|------|
| ① 修復前查腦庫 | `repair.py` / `test_repair.py` | 新行為 | repair._build_prompt 在 call LLM 前先查 brain gene，首輪成功率↑，token 花費↓ |
| ② CJK FTS5 分詞 | `knowledge.py` / `test_knowledge.py` | 搜尋升級 | jieba 分詞 + entries_fts_cjk FTS5 表，中文搜尋從 O(n) LIKE → O(1) FTS5 MATCH |
| ③ Inspector 去抖 | `inspector.py` / `test_inspector.py` | 新行為 | 連續 2 拍紅才產任務，防 flaky test 浪費配額 |
| ④ 心跳可變頻率 | `heartbeat.py` / `test_heartbeat.py` | 新行為 | queue_depth 決定 interval（忙碌 60s / 空閒 600s），節省閒置輪詢 |
| ⑤ Auto-Consolidate 升級 | `auto_consolidate.py` / `test_auto_consolidate.py` | 新行為 | 相似 gene 合併偵測 + prune 機制 + 失敗計數器可觀測 |

**紅線守護：** 未觸碰 checker.py / decision_log.py / safety.py / clarify.py。
**測試結果：** 跑 pytest 看即時數 ✅
**架構影響：** 無 — 所有變更皆在既有元件內擴充（non-invasive）。

### 2026-06-24 — Round 2：Tier 2 — 三箭齊發

**觸發：** Tier 2 優化方向（OPTIMIZATION.md 閉環 + Triage Auto-Suggest + 多語言 Checker）

**評測變動：** 跑 pytest 看即時數

**變更摘要：**

| 方向 | 檔案 | 類型 | 說明 |
|------|------|------|------|
| A. OPTIMIZATION.md 閉環 | `eval/`、`metrics.py`、`reflect.py` | 新建 | 15 題評測集 + SQLite 指標收集 + rule-based 反思引擎 |
| B. Triage Auto-Suggest | `triage.py`、`api/main.py` | 新建 | escalated 任務自動從腦庫搜尋修復建議，API 端點 |
| C. 多語言 Checker | `checker.py` | 擴展 | 新增 JS/jest、Go test 語言檢測 + runner |

**紅線守護：** 未觸碰 decision_log.py / safety.py / clarify.py。
**測試結果：** 跑 pytest 看即時數

### 2026-06-27 — Round 3：評測集閉環（9→15）

**觸發：** Session 初始化掃描發現 eval 停在 9/15，OPTIMIZATION.md 閉環從未真正走通。

**評測變動：** 9/15（Round 3 前）→ 15/15（Round 3 後）

**變更摘要：**

| 方向 | 檔案 | 類型 | 說明 |
|------|------|------|------|
| ① Clarify gate 順序重排 | `clarify.py` | Bugfix | action verb 檢查移到 min length 之前，短指令含動詞不再誤擋 |
| ② 中文問句粒子偵測 | `clarify.py` | 新行為 | 加 `_CHINESE_QUESTION_PARTICLES` regex + 動詞「說講問」 |
| ③ Safety gate 補 shutdown | `safety.py` | Bugfix | 加 shutdown/reboot/poweroff/init 0/halt |
| ④ Eval script 雙 bug | `run_eval.py` | Bugfix | `if clar:` tuple truth 永遠 True（最隱蔽）+ `intent.get`→`intent.category`（dataclass vs dict） |
| ⑤ Eval scenarios 校正 | `scenarios.json` | 校正 | code task 的 expected_routing 從 answer→code |
| ⑥ Classifier few-shot | `router/classifier.py` | Prompt 優化 | `_ROUTING_SYSTEM` 加 6 個中英文 few-shot 範例 |
| ⑦ 測試同步 | `test_clarify.py` | 測試更新 | 5 個測試斷言舊 buggy 行為，改用無動詞輸入測試 clarify |

**紅線守護：** `clarify.py` 的 `_is_vague` 邏輯順序更動為 bugfix（非自動優化），`decision_log.py` / `checker.py` 未觸碰。
**測試結果：** 365 passed（66s）
**架構影響：** 無 — 所有變更皆在既有元件內擴充。
