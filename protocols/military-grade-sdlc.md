# 協議：軍規工作流 — Military-Grade SDLC

> **用途**：分級開發流程，最小成本、最嚴驗收。
> **來源**：SPEC→guard→IMPL 軍工級工作法，精簡為三級。
> **套用範圍**：所有含程式撰寫的任務。

---

## 分級

啟動任務時先宣告等級：

```
L1 快速修 — typo、README、一行邏輯、重命名、已知道路的小改
L2 標準   — bug fix、新功能、跨 1-3 檔案的修改（預設）
L3 嚴謹   — 新 module、新 domain、架構變動、涉及多層（API+DB+frontend）
```

等級由 Scream 判斷。判斷錯誤 → 用戶糾正後降級或升。

---

## L1 快速修

```
流程：        直接修 → guard
前置 SPEC：   無
Guard：       pytest 相關測試（如有）
完成宣告：   1 行摘要
```

### 限制
- 不改 public API 簽名
- 不改資料結構 / DB schema
- 不改核心邏輯（checker / safety / clarify / decision_log）
- 違反任一 → 升 L2

---

## L2 標準（預設）

```
流程：        SPEC → IMPL → guard:all
SPEC：        3-5 行書面
Guard：       pytest 全跑
完成宣告：    guard 全過 → 1 行摘要
```

### SPEC 模板

任務開始時，在 TodoList 第一條或任務描述區寫：

```
SPEC
  why:    <為什麼要做>
  what:   <要做什麼>
  acceptance: <可驗收的條件，1-2 行>
  boundaries: <不做的範圍，選用>
  guards: <pytest | pytest+type | 選用>
```

範例：

```
SPEC
  why:    search tool 讓 agent 能搜網路
  what:   DuckDuckGo HTML parser + /search API
  acceptance: POST /search 回傳 {query, results[], count}，results 含 title/url/snippet
  boundaries: 不接 LLM、不存搜尋歷史
  guards: pytest
```

規格在執行中可修正，但每次修正後通知用戶。

### Guard 層

當前專案 guard 設定（`pyproject.toml` 無 lint/type 工具時）：

```yaml
guards:
  pytest: "python -m pytest tests/ -v --tb=short"
```

缺少的 guard 不強制，但要記錄：

```
⚠ missing guard: ruff (lint) — 不在依賴中，跳過
⚠ missing guard: mypy (type) — 不在依賴中，跳過
```

Guard 全過或跳過完成後 + acceptance criteria 滿足 = 任務完成。

---

## L3 嚴謹

```
流程：        SPEC → contract → IMPL → guard:all
SPEC：        完整 5-8 行（含 io_example、edge cases）
Contract：    介面定義（Pydantic model / type stub / API schema）
Guard：       pytest 全跑 + 手動檢查邊界案例
完成宣告：    guard 全過 + 3 行摘要含邊界案例驗證
```

用於：
- 新 executor type（如上次加 web-llm-genspark）
- 新 API endpoint 牽涉多層
- 跨 session 架構變動

---

## 驗收矩陣

| 等級 | spec 長度 | guard | 總耗時 |
|------|----------|-------|--------|
| L1 | 0 行 | 選用 | <1 分 |
| L2 | 3-5 行 | pytest | 2-8 分 |
| L3 | 5-8 行 + contract | pytest + 邊界 | 10-20 分 |

---

## 退出條件

任何等級遇到以下情況 → escalate：

- guard 連續 3 次不過且進步不明顯
- 發現前置依賴不存在（如 API key missing）
- 用戶要求改方向
- SPEC 的 `boundaries` 被突破

---

## 跟現有協議的關係

| 現有協議 | 關係 |
|----------|------|
| task-breakdown.md | L3 配套。大任務先拆解，拆後每個子任務掛各自等級 |
| caveman-ponytail skill | 正交疊加。caveman 壓縮 prose/ponytail 壓縮程式 → military-grade 管流程 |

---

## 紅線

- 不改 `checker.py` / `decision_log.py` / `safety.py` / `clarify.py` 核心邏輯（PROJECT.md rule 4）
- L2 強制 SPEC，不可跳過。自覺「太簡單不用寫」→ 降 L1
- Guard 失敗不可偽造完成