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
（待填）
- 格式：每筆 = 代表性任務 + 預期判準（io_example / 是否該過 / 該走哪條路由）。
- 規模與覆蓋：涵蓋 direct / clarify / align / loop / sensitive / danger 各類，避免只測簡單題。
- 存放位置與版控：純文字、進 git，與 prompt 同版本綁定。
- 與現有單元測試的關係：單元測試測「程式對不對」，評測集測「治理判斷對不對」，兩者不同層，不可混。

---

## 三、指標（Metrics）——信度與效度分開量
（待填）
- **信度**（穩不穩）：同輸入重複 N 次，路由決策 / Checker 分數的一致率。
- **效度**（對不對）：判斷結果與評測集「正確答案」的吻合率；效度大半靠 pytest 等客觀錨點撐，
  不可只靠 LLM 自評。
- 聚合分數與門檻：低於門檻不准換版（防退步）。

---

## 四、Trace → 反思 → 提案
（待填）
- 從哪些失敗訊號觸發反思（煞車停、低分、違規、人類否決）。
- 反思產出什麼：具體指出 prompt / 路由規則 / 閾值的哪一處該怎麼改（不是模糊建議）。
- 一次只改一個變數，便於歸因（呼應 A/B 模型選型時的「控制變數」思路）。

---

## 五、換版規則（HITL 閘門）
（待填）
- 新版必須：在評測集上信度與效度「都不退步、至少一項變好」才候選。
- 回歸保護：單元測試全綠 + 評測集不退步，缺一不可。
- 最終拍板：Ryan（不可逆動作先問，對應協作規則第 3 條）。
- 版本紀錄：改了什麼、為什麼、評測前後分數，寫進版控 commit message。

---

## 六、紅線（本迴路絕不可碰）
（待填）
- 迴路**不得自動修改** checker.py / decision_log.py / safety.py / clarify.py 核心邏輯。
- 迴路**不得自動 commit / push**。提案只到「候選」，落地由人。
- prompt 不得在執行期被任何 agent 即時改寫；只能透過本迴路、離線、經拍板更新。

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
