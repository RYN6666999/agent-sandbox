# Verdict 契約 — agent-sandbox ↔ neuralis bridge 接縫

> 目的：釘死「評分路由器（agent-sandbox，Scream 做）」與「shadow/audit bridge
> （neuralis，另一手做）」之間的資料接縫，讓兩邊平行開發**不改對方的檔**。
> 這是 Stage 3.5（見 neuralis `docs/specs/scoring-router-canary.md`）的實作契約。
>
> 兩邊只跟契約。契約要改 → 先在本檔改定義，兩邊再各自跟。

---

## 鐵則：擴充，不要重造

agent-sandbox **已有** verdict 概念（`orchestrator/runner.py` / `loop.py`：pass / escalate /
retry）+ `contracts/`（task_spec、interface_contract、routing_triple、dept_output）+ `router/`
（classifier、policy、rules）。**先讀這些，在既有 verdict 上加欄位**，不要另起一套。

既有 verdict dict（from `loop.py:49-56`）：
```python
{
    "status": "pass" | "retry" | "escalate",
    "score": float,
    "feedback": str,
    "passed": bool,
    "source": "pytest" | "claude-cli",
    "violations": list,
}
```

Verdict v2 **疊加**新欄位，保持與既有 verdict 相容。

---

## 兩個訊息

### 1. ActionRequest（neuralis bridge → agent-sandbox）

Aris 想做的動作，送進來評分/沙箱。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `action_id` | `str` | 唯一 id（冪等鍵可複用既有 idempotency 慣例） |
| `task_class` | `str` | 任務類名（對應分類表，如 `file_write` / `network_call`） |
| `payload` | `dict` | 要跑的東西（命令/參數），內容不入 log 全文 |
| `workspace` | `str` | 沙箱工作區路徑（限 sandbox workspace 內） |
| `declared_reversibility` | `enum` `"containable"` / `"escaping"` | 呼叫端自報，裁判會覆核 |
| `cost_estimate` | `dict` | `{"tokens"?: int, "compute"?: int}` 預估 |
| `ts` | `str` | ISO-8601 請求時間戳 |

### 2. Verdict v2（agent-sandbox → neuralis bridge）

= 既有 verdict 欄位 **＋** 下列 delta。bridge 只讀，不改。

**既有欄位（保留，來自 loop.py）：**

| 欄位 | 型別 | 說明 |
|------|------|------|
| `action_id` | `str` | 對回 ActionRequest |
| `status` | `enum` `"pass"` / `"retry"` / `"escalate"` | 沿用既有 verdict 值域 |
| `score` | `float` | 評分分數（0.0-1.0 或 0.0-10.0，視實作） |
| `feedback` | `str` | 評分回饋說明 |
| `passed` | `bool` | 是否通過 |
| `source` | `str` | 評分來源（如 `"scoring-router"`） |
| `violations` | `list` | 違規列表 |

**delta 欄位（v2 新增）：**

| 欄位 | 型別 | 說明 |
|------|------|------|
| `lane` | `enum` `"deny"` / `"human"` / `"sandbox"` / `"auto"` | **路由器判的路**（四選一） |
| `outcome` | `enum` `"pass"` / `"fail"` / `"error"` | 沿用既有 verdict 值域，缺則擴充 |
| `reversible_actual` | `enum` `"containable"` / `"escaping"` | **裁判覆核後的真值**，非自報 |
| `objective_signal` | `dict` | 證明它對的客觀訊號：`{"kind": "pytest"|"goal_met"|..., "detail": ...}` |
| `cost_actual` | `dict` | `{"tokens": int, "compute": int}` 實際用量（接 E2 ledger） |
| `committed` | `bool` | 沙箱跑完落地(`true`) 或撤回(`false`) |
| `gate` | `dict` | `{"decision": "allow"|"deny"|"escalate", "reason": str}` |
| `digest` | `str` | hash + 截斷 redact 頭，**不落全文**（沿用 shadow 07-23 `_result_digest` 慣例） |
| `ts` | `str` | ISO-8601 評分時間戳 |

---

## 誰寫哪邊（平行不打架）

| 側 | repo | 動的檔 |
|----|------|--------|
| **Scream** | `~/agent-sandbox` | `contracts/verdict_v2.py`（Verdict v2 schema）· `router/scoring.py`（scoring + lane）· `router/reversibility.py`（分類表 loader）· `router/ratchet.py`（信任 ratchet）· `router/orchestrate.py`（串接）· `tests/` |
| **另一手** | `~/Developer/neuralis` | bridge 的 shadow/audit reader（照本契約讀 Verdict） |

**兩邊都不改對方的檔。** 只透過本契約的 schema 對接。

---

## 不變量

1. **被評分的動作本身，不得 import 或 patch 路由器/裁判/評分規則。** 裁判與被審者物理隔離。
2. `digest` 一律不落全文（隱私）。
3. **裁判覆核 `reversible_actual`，不信呼叫端自報的 `declared_reversibility`。**
4. `lane` 決定權在 agent-sandbox 的路由器，bridge 只讀。
5. 契約要改 → 先更新本檔，兩邊再各自跟進，**不單方面改 schema**。

---

## 路由映射表（route_key → task_class → op_name）

這是 bridge（`agentos-aris-bridge.py`）和 canary（`sandbox_canary.py`）之間的共用映射，單一來源在 `router/canary_adaptor.py`。

### route_key → task_class（bridge 側）

| route_key | task_class | 可回退性 | 說明 |
|-----------|-----------|---------|------|
| `read` | `file_write` | containable | 讀檔 |
| `write` | `file_write` | containable | 寫檔 |
| `branding-template` | `file_write` | containable | 模板產出 |
| `bash` | `compute_draft` | containable | 執行指令 |
| `compile` | `local_test` | containable | 編譯/測試 |
| `code` | `refactor_local` | containable | 改程式碼 |
| `engineer` | `refactor_local` | containable | 工程任務 |
| `design` | `compute_draft` | containable | 設計 |
| `plan` | `compute_draft` | containable | 規劃 |
| `spec-mgmt` | `compute_draft` | containable | 規格管理 |
| `security` | `compute_draft` | containable | 安全掃描 |
| `troubleshoot` | `compute_draft` | containable | 除錯 |
| `motion` | `compute_draft` | containable | 動畫 |
| `research` | `network_call` | escaping | 研究/網路 |
| `search-web` | `network_call` | escaping | 網路搜尋 |
| `browser-research` | `network_call` | escaping | 瀏覽器研究 |
| `sports` | `network_call` | escaping | 運動資料 |
| `social-scrape` | `network_call` | escaping | 社群爬蟲 |
| `video` | `costly_compute` | escaping | 影片/高成本 |
| `html-video` | `costly_compute` | escaping | HTML 影片 |
| `aris-status` | `gbrain_read` | containable | 內部狀態 |
| *未列在表上* | `unknown` | escaping → human | 最嚴安全預設 |

### task_class → op_name（canary 側，來自 `canary_adaptor.TASK_CLASS_TO_OPERATION`）

| task_class | op_name | 對應執行函式 | 說明 |
|-----------|---------|-------------|------|
| `file_write` | `write_file` | `_execute_file_write` | 沙箱內寫檔，有 path escape 檢查 |
| `local_test` | `pytest` | `_execute_pytest` | 沙箱內跑 pytest，有 timeout |
| `compute_draft` | `compute` | `_execute_compute_draft` | 沙箱內執行 shell，阻擋網路指令 |
| `refactor_local` | `compute` | `_execute_compute_draft` | 同 compute |
| `brief_draft` | `compute` | `_execute_compute_draft` | 同 compute |
| `gbrain_read` | `compute` | `_execute_compute_draft` | 同 compute |

### payload.operation（bridge → canary）

bridge 的 `_build_action_request()` 會從 `canary_adaptor.resolve_operation()` 查表，
自動設定 `payload["operation"]`。canary 收到後優先使用 `payload.operation`，
若無則從 registry 查 `task_class` 對應的 operation。

**不在 registry 上的 task_class 不支援 canary 執行**，sandbox lane 會回傳
`unsupported operation` 並 escalate 回 human lane。