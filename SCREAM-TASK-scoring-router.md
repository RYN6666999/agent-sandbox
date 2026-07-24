# Scream 任務：評分路由器 + 信任 ratchet（agent-sandbox）

> 甲（安全自我進化）Stage 3.5。你在 `~/agent-sandbox` 蓋「決定 Aris 哪些動作能自動、
> 哪些要問人」的裁判層。**現階段是休眠鷹架**：蓋好、測綠、等 Ryan review，**不上線**。
>
> 本 brief 是 `~/Developer/neuralis/docs/specs/scoring-router-canary.md` 的落地指令。
> 所有 spec 決策以該檔為準（2026-07-24 定版），本 brief 提煉其執行面。

---

## 🔴 硬邊界（不可越）

1. **只在 `~/agent-sandbox` 動手。** 絕不碰 `~/Developer/neuralis`（那是另一手 + Aris 的腦）。
2. **不接真 executor、不讓任何東西自動上線。** 你蓋的是鷹架，不是啟用。
3. **裁判不下場：** 被評分的動作**不得** import/patch 路由器、ratchet、評分規則。物理隔離。
4. **不動既有測試的斷言去遷就實作；** 壞了是實作的事。
5. **ratchet 絕不自動把任何任務類升到 `auto`。** 畢業 auto 必過 Ryan 一次性簽核
   （發 `needs_ryan_signoff` 事件，等待外部簽核）。
6. **不動 `orchestrator/` 既有 verdict 邏輯。** 你擴充（疊 v2 欄位），不重寫。

---

## 先讀（別憑空造）

既有結構，你接的都不是綠地：

| 要讀的 | 路徑 | 為什麼 |
|--------|------|--------|
| 既有 verdict | `orchestrator/runner.py:177-196` | `run_verification()` 回 `{"status": "pass"/"retry"/"escalate", "score", "feedback", ...}` |
| loop 介面 | `orchestrator/loop.py:21-56` | `run_verification()` 單次驗收循環，看懂 verdict dict 結構 |
| 既有路由 | `router/classifier.py` | 7-category + 3-way routing 分類，你擴充分類表 loader |
| 政策引擎 | `router/policy.py` | 既有 policy `enforce()` 模式，你加 scoring 政策 |
| 規則引擎 | `router/rules.py` | keyword rule matching 模式 |
| 既有 contracts | `contracts/task_spec.py` | pydantic BaseModel + field_validator 風格 |
| 既有 contracts | `contracts/routing_triple.py` | 同上，pydantic 風格 |
| 既有 contracts | `contracts/interface_contract.py` | 同上 |
| 既有 contracts | `contracts/dept_output.py` | Literal 列舉 + pydantic 風格 |
| 測試風格 | `tests/test_contracts.py` | pytest，`sys.path.insert(0, ...)`，`pytest.raises(ValidationError)` |
| 測試風格 | `tests/test_router.py` | 同上，匯入 router 模組直接測 |
| 接縫契約 | `docs/verdict-contract.md` | **Verdict v2 欄位以它為準**，兩邊只跟契約 |
| 沙箱 | `data/` | 持久化目錄（ratchet 狀態放這裡） |
| 分類表 spec | `canary spec §2` | 初版分類表（Ryan 2026-07-24 拍，見下方 B3） |

---

## 要蓋的區塊

### B1 — Verdict v2（`contracts/` 新增 `verdict_v2.py`）

在既有 `orchestrator/loop.py` 的 verdict dict 上加 `docs/verdict-contract.md` 列的 delta 欄位。
**擴充，不重造。** 既有 verdict 是 dict（`{"status", "score", "feedback", "passed", "source", "violations"}`），
v2 疊加新欄位後保持相容。

用 pydantic BaseModel，命名 `VerdictV2`，放在 `contracts/verdict_v2.py`。

Delta 欄位（詳見 `docs/verdict-contract.md` Verdict v2 表）：
- `lane: Literal["deny", "human", "sandbox", "auto"]`
- `reversible_actual: Literal["containable", "escaping"]`
- `objective_signal: dict` — `{kind: "pytest"|"goal_met"|..., detail}`
- `cost_actual: dict` — `{tokens, compute}`
- `committed: bool`
- `gate: dict` — `{decision: "allow"|"deny"|"escalate", reason}`
- `digest: str` — hash + 截斷 redact 頭，不落全文
- `ts: str` — ISO-8601

既有欄位（from loop.py）保留：`status`, `score`, `feedback`, `passed`, `source`, `violations`。

---

### B2 — 評分函式（`router/` 新增 `scoring.py`）

四維打分 → 四 lane。純函式、可測。**不碰 LLM，不碰網路。**

```python
# 簽名
def score(request: ActionRequest) -> VerdictV2:
    ...
```

四維與評分邏輯：

| 維度 | 問什麼 | 高分 = |
|------|--------|--------|
| **可回退性** | 壞了收得回嗎？ | 任務類屬「關得住」組（沙箱可撤） |
| **可驗證性** | 有客觀訊號證明它對嗎？ | 有 pytest / 任務達標 / held-out 分 |
| **信心 × 歷史** | Aris 多確定 + 這類**以前被驗證對過幾次** | 同類 ratchet 驗證成功累積多 |
| **成本** | 燒多少 token/算力（接 E2 ledger） | 在預算內 |

四條 lane 決定邏輯：

```
lane = deny        ← 碰腦/碰裁判/爆硬預算（硬拒，不問分數）
lane = human       ← 潑得出去（escaping）或 沒法驗證 或 信心低 或 全新任務類
lane = sandbox     ← containable + 可驗證 + 歷史夠 but 未畢業 auto
lane = auto        ← containable + 可驗證 + 歷史夠 **且已簽核進 auto**
```

**可回退性是硬地板，不是分數。** 「潑得出去」類永遠封頂 human，履歷再厚不自動畢業。

---

### B3 — 分類表 → reversibility loader（`router/` 新增 `reversibility.py`）

從分類表決定「可回退性」：`containable` / `escaping`。

**初版分類表（Ryan 2026-07-24 拍）：**

| 類別 | 任務 | 可回退性 | 預設路由上限 |
|------|------|----------|------------|
| 🟢 關得住 | 本地檔案寫入/編輯（sandbox workspace 內） | `containable` | 可畢業到 `auto` |
| 🟢 關得住 | 純計算/分析/草稿生成 | `containable` | 可畢業到 `auto` |
| 🟢 關得住 | 本地程式碼重構 | `containable` | 可畢業到 `auto` |
| 🟢 關得住 | gbrain 讀取（query/get/search） | `containable` | 可畢業到 `auto` |
| 🟢 關得住 | 產 morning brief 草稿（只產不發） | `containable` | 可畢業到 `auto` |
| 🟢 關得住 | 跑本地測試（pytest） | `containable` | 可畢業到 `auto` |
| 🟠 潑得出去 | 網路請求/外部 API | `escaping` | **永遠封頂 human** |
| 🟠 潑得出去 | 花錢/大量付費 token | `escaping` | **永遠封頂 human** |
| 🟠 潑得出去 | 發訊息（LINE/TG/email） | `escaping` | **永遠封頂 human** |
| 🟠 潑得出去 | git push/遠端 repo | `escaping` | **永遠封頂 human** |
| 🟠 潑得出去 | launchd/系統設定/gbrain 外的外部狀態 | `escaping` | **永遠封頂 human** |
| ⚪ 邊界 | gbrain 寫入（put_page） | `escaping` | **預設 human**，放寬待 Ryan 拍 |

**新任務類預設歸 `escaping`/human**，直到證明可關得住。

實作：`def classify_reversibility(task_class: str) -> Literal["containable", "escaping"]`
從分類表查，不在表上的回 `escaping`。

---

### B4 — 信任 ratchet（`router/` 新模組 `ratchet.py`，狀態持久化到 `data/`）

每任務類一條信任履歷：

```
一個新任務類：human →（沙箱累積驗證成功）→ sandbox →（夠厚）→ auto
              人每次都管         人不管單次、它在攢履歷        人完全不用管
```

**ratchet 規則：**

1. **只靠客觀驗證成功爬升**（不是自報、不是「以前批准過」）。
2. **不對稱：難爬易崩** — 做對慢慢加；一次 fail/divergence → 大扣或直接降級。
3. **最小樣本閘：** 畢業要過樣本數下限 + 信賴區間，不是連過 N 次就升。
4. **狀態機：** `human → sandbox → auto`
5. **🔑 policy (b)（Ryan 拍）：** 畢業進 `auto` 不自走 —— 發 `needs_ryan_signoff` 事件，
   等 Ryan 一次性簽核才真的進 auto。**ratchet 自己絕不把任何類升到 auto。**

```python
# 簽名
class RatchetEntry(BaseModel):
    task_class: str
    level: Literal["human", "sandbox", "auto"]
    verified_count: int
    failed_count: int
    last_verified_at: str | None
    needs_signoff: bool  # True = pending Ryan approval to enter auto

def load_ratchet() -> dict[str, RatchetEntry]:
    """從 data/ratchet.json 讀取所有任務類的信任狀態。"""

def save_ratchet(entries: dict[str, RatchetEntry]) -> None:
    """寫回 data/ratchet.json。"""

def update_ratchet(entry: RatchetEntry, passed: bool) -> RatchetEntry:
    """一次驗證成功或失敗後，更新信任履歷並決定是否觸發狀態轉移。
    若升級到 auto，設 needs_signoff=True 並發事件（不直接升）。"""
```

**事件格式（寫入 `data/ratchet_events.log`，JSONL）：**
```json
{"ts": "...", "event": "needs_ryan_signoff", "task_class": "file_write", "verified_count": 30}
```

---

### B5 — 串接（`router/` 新增 `orchestrate.py` 或整合到現有路由）

路由器讀 Verdict → 更新 ratchet 履歷。全在本 repo 內，不跨 neuralis。

```python
def process_verdict(request: ActionRequest, verdict: VerdictV2) -> None:
    """收到 Verdict v2 後：
    1. 如果 verdict.committed == True → 更新 ratchet（成功/失敗）
    2. 檢查是否有任務類需要發 signoff 事件
    3. 寫審計 digest
    """
```

---

## 分類表（集中一覽）

| 任務類關鍵字 | 可回退性 | 路由上限 | 備註 |
|-------------|----------|---------|------|
| `file_write` | `containable` | 可畢業 auto | 限 sandbox workspace |
| `compute_draft` | `containable` | 可畢業 auto | 純計算/分析/草稿 |
| `refactor_local` | `containable` | 可畢業 auto | 本地重構 |
| `gbrain_read` | `containable` | 可畢業 auto | query/get/search |
| `brief_draft` | `containable` | 可畢業 auto | 只產不發 |
| `local_test` | `containable` | 可畢業 auto | pytest |
| `network_call` | `escaping` | **永遠 human** | 外部 API |
| `costly_compute` | `escaping` | **永遠 human** | 花錢/大量 token |
| `send_message` | `escaping` | **永遠 human** | LINE/TG/email |
| `git_push` | `escaping` | **永遠 human** | 遠端 repo |
| `system_change` | `escaping` | **永遠 human** | launchd/系統設定 |
| `gbrain_write` | `escaping` | **預設 human** | 邊界，放寬待拍 |
| `*`（未知） | `escaping` | **永遠 human** | 預設最嚴 |

---

## 不要做

- ❌ 接真 Scream executor（那是後面 Ryan 親自把關的事）
- ❌ 碰 neuralis / laap
- ❌ 讓 ratchet 自動升到 auto（必過 Ryan 簽核）
- ❌ 把 verdict 全文寫進 log（只 digest）
- ❌ 改既有 `orchestrator/` 的 verdict 邏輯（擴充，不改）
- ❌ 改 `docs/verdict-contract.md` 的 schema（要改先跟另一手講）
- ❌ 引入 LLM 呼叫（評分是純函式）
- ❌ 改 `contracts/` 既有檔案（你新增 `verdict_v2.py`，不修改存檔）

---

## 驗收

- `pytest` 全綠（擴 `tests/`，照既有風格，`sys.path.insert(0, ...)` + pydantic + pytest）
- 每個區塊有測試，特別涵蓋：
  - ratchet **不對稱升降**（一次 fail 扣分 > 一次 pass 加分）
  - **最小樣本閘**（未達樣本數下限不升級）
  - **policy(b) 不自動升 auto、發 signoff 事件**
  - 分類表 escaping 類**打不進 sandbox/auto**（永遠 human）
  - VerdictV2 delta 欄位序列化/反序列化
  - 裁判隔離：一條測試證明「被評分動作無法改到評分規則」
  - 新任務類預設 `escaping`/human
- 收工回報：動了哪些檔、pytest 結果、有無碰到契約要改（要改先講，不自己改 neuralis 那側）