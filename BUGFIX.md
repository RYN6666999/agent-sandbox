# BUGFIX — Debug 記錄與修復策略

> 記錄日期：2026-06-21
> 執行者：Opus（GenSpark AI Developer）
> 觸發方式：Ryan 要求「梳理整個 repo，嘗試 debug 還有理解這個專案的立意」

---

## 概覽

從 0 開始全面閱讀 repo，跑 `pytest tests/` 發現 **16 個失敗測試**。
分析後確認：**全部是測試程式碼落後於 v3 架構重構的「測試債」**，
不是 production code 的邏輯 bug（生產代碼本身的設計是正確的）。

**修復結果：16 failed → 248 passed, 1 skipped（環境依賴）, 0 failed**

---

## 失敗清單（修復前）

```
FAILED tests/test_agnes.py::test_executors_includes_agnes
FAILED tests/test_api.py::test_models_returns_list
FAILED tests/test_api.py::test_task_run_success
FAILED tests/test_api.py::test_task_run_executor_sets_spec
FAILED tests/test_checker.py::TestLlmFallbackMarker::test_text_output_marked_llm_scored
FAILED tests/test_checker.py::TestLlmFallbackMarker::test_code_without_tests_marked_llm_scored
FAILED tests/test_orchestrator.py::test_checker_keyword_miss_fails_immediately
FAILED tests/test_orchestrator.py::test_checker_boundary_violation_fails
FAILED tests/test_orchestrator.py::test_checker_no_progress_detected
FAILED tests/test_orchestrator.py::test_checker_pass_when_score_high
FAILED tests/test_orchestrator.py::test_loop_passes_on_high_score
FAILED tests/test_orchestrator.py::test_loop_escalates_on_max_rounds
FAILED tests/test_orchestrator.py::test_loop_escalates_on_no_progress_streak
FAILED tests/test_orchestrator.py::test_loop_retries_before_passing
FAILED tests/test_search.py::test_executors_includes_web_search
FAILED tests/test_skill_bridge.py::test_scan_finds_real_skills
```

---

## Bug 分類與詳細分析

### Bug 1 — `web-search` / `agnes-*` executor 未被自動注冊（最嚴重）

**影響測試（3 項）：**
- `tests/test_search.py::test_executors_includes_web_search`
- `tests/test_agnes.py::test_executors_includes_agnes`（含 agnes-analyze/image/video/web-search）

**錯誤訊息：**
```
AssertionError: assert 'web-search' in ['claude-code']
AssertionError: assert 'agnes-analyze' in ['claude-code']
```

**根本原因分析：**

`orchestrator/executor_registry.py` 的 `_BUILTIN_EXECUTORS` 只有 `claude-code` 一個條目。
`web-search`、`agnes-analyze`、`agnes-image`、`agnes-video` 只有各自的 CLI wrapper 腳本（`scripts/search-web.py` 等），但從未被注冊進 registry。

`_init()` 函式在 module 載入時只會：
1. 把 `_BUILTIN_EXECUTORS` 的內容注冊進 `_registry`
2. 讀取 `settings.json` 的 `executors` 欄位並注冊

但 `settings.json` 的 `executors` 欄位是空物件 `{}`，所以 `web-search` 等 executor 永遠不會出現在 registry。

這不只是測試問題——**`GET /search`、`POST /vision/analyze`、`POST /image/generate`、`POST /video/generate` 這些 API 端點在 production 也是壞的**，全部會拋出 `KeyError: "Executor 'web-search' not registered"`。

**推測原因：** v3 重構時把 executor 從 `settings.json` 的動態設定改為程式碼內建，但開發者忘記同步把它們加進 `_BUILTIN_EXECUTORS`，形成「有 wrapper、無注冊」的死角。

**修復策略：** 在 `orchestrator/executor_registry.py` 的 `_BUILTIN_EXECUTORS` 中靜態定義四個 executor，使用 `sys.executable` 作為 binary（確保跨虛擬環境），路徑用 `Path(__file__).parent.parent / "scripts"` 計算絕對路徑。

**修改檔案：** `orchestrator/executor_registry.py`

```python
# 新增至 _BUILTIN_EXECUTORS
"web-search": {
    "name": "web-search",
    "binary": sys.executable,
    "flags": [str(_SCRIPTS_DIR / "search-web.py")],
    "timeout": 30,
    "type": "subprocess",
},
"agnes-analyze": { ... },
"agnes-image":   { ... },
"agnes-video":   { ... },
```

---

### Bug 2 — `/models` API 回傳格式與測試不一致

**影響測試（1 項）：**
- `tests/test_api.py::test_models_returns_list`

**錯誤訊息：**
```
AssertionError: assert 'models' in {'free': [], 'paid': ['claude-opus', 'claude-sonnet', ...]}
```

**根本原因分析：**

`api/main.py` 的 `list_models()` 回傳 `{"free": [...], "paid": [...]}` 兩層結構，
但測試在驗證舊格式 `{"models": [...]}` 的 flat list。
推測某次重構把 `/models` 端點改成分層格式（方便 UI 顯示免費/付費），測試沒有同步。

**修復策略：** 更新測試配合新格式（保留 API 不動，API 格式資訊量更豐富）。

**修改檔案：** `tests/test_api.py`

```python
# 改為驗證實際格式
assert "free" in body
assert "paid" in body
assert isinstance(body["paid"], list)
assert len(body["paid"]) > 0
```

---

### Bug 3 — `test_api.py` patch 對象名稱過期：`run_loop` → `run_maker`

**影響測試（2 項）：**
- `tests/test_api.py::test_task_run_success`
- `tests/test_api.py::test_task_run_executor_sets_spec`

**錯誤訊息：**
```
AttributeError: <module 'api.main'> does not have the attribute 'run_loop'
```

**根本原因分析：**

v3 重構後，`api/main.py` 的 `/task/run` 端點改為呼叫 `run_maker`（來自 `orchestrator.maker`），
而非舊版的 `run_loop`（已從 import 中移除）。
測試 `patch("api.main.run_loop")` patch 的是一個不存在的名稱，必然失敗。

**修復策略：** 把 patch 目標從 `api.main.run_loop` 改為 `api.main.run_maker`，
並把 `mock.return_value` 從原本的 dict 格式改為 `run_maker` 實際回傳的字串格式。

**修改檔案：** `tests/test_api.py`

```python
# 修復前
with patch("api.main.run_loop") as mock_loop_run:
    mock_loop_run.return_value = {"status": "done", "output": "def hello(): pass", ...}

# 修復後
with patch("api.main.run_maker") as mock_maker:
    mock_maker.return_value = "def hello(): pass"
```

---

### Bug 4 — 測試 patch 已被 v3 刪除的 `_llm_score` 函式

**影響測試（8 項）：**
- `tests/test_checker.py::TestLlmFallbackMarker::test_text_output_marked_llm_scored`
- `tests/test_checker.py::TestLlmFallbackMarker::test_code_without_tests_marked_llm_scored`
- `tests/test_orchestrator.py::test_checker_no_progress_detected`
- `tests/test_orchestrator.py::test_checker_pass_when_score_high`
- `tests/test_orchestrator.py::test_checker_keyword_miss_fails_immediately`
- `tests/test_orchestrator.py::test_checker_boundary_violation_fails`
- `tests/test_orchestrator.py::test_loop_passes_on_high_score`（import `from orchestrator.loop import run`）
- `tests/test_orchestrator.py::test_loop_*`（共 4 項）

**錯誤訊息：**
```
AttributeError: <module 'orchestrator.checker'> does not have the attribute '_llm_score'
ImportError: cannot import name 'run' from 'orchestrator.loop'
AssertionError: assert 'missing expected keywords' in '[CLAUDE-CLI | text output] error: ...'
```

**根本原因分析：**

這是本次修復中最多項目的 bug 類，源頭是同一個 v3 決策（D1、D23）：

1. **`_llm_score` 刪除**：D1 決策明確要求「移除 LLM 評分 fallback」，`checker.py` 已改為：
   - 有測試的 Python 程式碼 → 真跑 pytest（`_pytest_check`）
   - 純文字或無測試程式碼 → delegate 給 Claude CLI（`_claude_cli_check`）
   
   但 `test_checker.py` 的 `TestLlmFallbackMarker` 仍在 patch 已不存在的 `_llm_score`。

2. **`_llm_check` 的 keyword/boundary 邏輯刪除**：`test_orchestrator.py` 的測試在驗證舊版 checker 的「比對關鍵字」和「偵測 boundary 違規」邏輯，這些邏輯在 v3 全部移除了（改由 Claude CLI 評判）。

3. **`run` 函式改名**：舊版 `loop.py` 有 `run()` 函式（包含完整 Maker/Checker 迴圈），v3 簡化為 `run_verification()`（單次驗收）。`test_orchestrator.py` 仍在 `from orchestrator.loop import run`。

**修復策略（分三部分）：**

**4a — `test_checker.py`** `TestLlmFallbackMarker` 改為 patch `_claude_cli_check`：
```python
from orchestrator.checker import CheckResult as CR
fake = CR(passed=True, score=8.0, feedback="[CLAUDE-CLI] good", source="claude-cli")
with patch("orchestrator.checker._claude_cli_check", return_value=fake):
    result = check(spec, text_output)
assert result.source == "claude-cli"
```

**4b — `test_orchestrator.py`** 舊版 checker 行為測試全部重寫，改為測試 v3 的實際語意：
- 文字輸出 → `_claude_cli_check` 被呼叫
- `claude-cli` 回高分 → `passed=True`
- `claude-cli` 回低分 → `passed=False`

**4c — `test_orchestrator.py`** loop 測試全部改用 `run_verification`，驗證三種停損條件：
- `score >= 7.0` → `status="pass"`
- `score = 2.0`（pytest fail）→ `status="retry"`
- `score = 0.0`（timeout/env error）→ `status="escalate"`

**修改檔案：** `tests/test_checker.py`、`tests/test_orchestrator.py`

---

### Bug 5 — `knowledge.py` / `blackboard.py` 使用已廢棄的 `datetime.utcnow()`

**影響：** DeprecationWarning（非 test failure，但 Python 3.12+ 警告，未來版本可能 error）

**位置：**
- `orchestrator/knowledge.py` 第 273 行、第 454 行：`__import__('datetime').datetime.utcnow()`
- `orchestrator/blackboard.py` 第 11 行：`datetime.utcnow()`

**根本原因：**

`datetime.utcnow()` 在 Python 3.12 標記為 deprecated，應改用 timezone-aware 的 `datetime.now(timezone.utc)`。
這兩個函式會在測試輸出中產生大量警告，影響測試結果可讀性。

**修復策略：** 統一替換為 `datetime.now(timezone.utc)`。

**修改檔案：** `orchestrator/knowledge.py`、`orchestrator/blackboard.py`

```python
# 修復前
datetime.utcnow().strftime(...)

# 修復後（blackboard.py）
datetime.now(timezone.utc).strftime(...)

# 修復後（knowledge.py，保留 __import__ 風格以維持一致性）
__import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime(...)
```

---

### Bug 6 — `test_scan_finds_real_skills` 在沙箱/CI 無條件失敗

**影響測試（1 項）：**
- `tests/test_skill_bridge.py::test_scan_finds_real_skills`

**錯誤訊息：**
```
AssertionError: notebooklm not found in []
assert 'notebooklm' in []
```

**根本原因分析：**

這個測試掃描 `~/.claude/skills/` 目錄並驗證 `notebooklm` 技能存在。
這個目錄只存在於 Ryan 的本機環境，在任何其他環境（CI、沙箱、新開發者機器）都不存在。
`orchestrator/skill_bridge.py` 的 `scan()` 在目錄不存在時會正常回傳 `{"skills": []}` 而非拋錯，
但測試沒有對這個情況做任何處理，直接 assert 失敗。

**修復策略：** 在測試開頭加 `pytest.skip()` 條件：如果 `CLAUDE_SKILLS_DIR` 不存在，直接 skip 並說明原因，不 fail。

**修改檔案：** `tests/test_skill_bridge.py`

```python
def test_scan_finds_real_skills():
    import pytest
    from orchestrator.skill_bridge import CLAUDE_SKILLS_DIR, scan

    if not CLAUDE_SKILLS_DIR.exists():
        pytest.skip(f"Claude skills dir not found: {CLAUDE_SKILLS_DIR}")
    
    # 以下是只在本機才執行的真實驗證
    ...
```

---

## 修改檔案彙整

| 檔案 | 類型 | 修改內容 |
|------|------|---------|
| `orchestrator/executor_registry.py` | **Production** | 在 `_BUILTIN_EXECUTORS` 加入 web-search / agnes-analyze / agnes-image / agnes-video，使用 `sys.executable` 確保跨虛擬環境 |
| `orchestrator/blackboard.py` | **Production** | `datetime.utcnow()` → `datetime.now(timezone.utc)` |
| `orchestrator/knowledge.py` | **Production** | `datetime.utcnow()` → `datetime.now(timezone.utc)`（兩處） |
| `tests/test_api.py` | **Test** | (1) `/models` 格式測試改驗 `free`/`paid`；(2) patch `run_loop` → `run_maker` |
| `tests/test_checker.py` | **Test** | `TestLlmFallbackMarker` 改 patch `_claude_cli_check` 而非已刪除的 `_llm_score` |
| `tests/test_orchestrator.py` | **Test** | 刪除舊版 keyword/boundary/progress checker 測試；刪除 `run()` loop 測試；改寫為驗證 `run_verification()` 三種停損 |
| `tests/test_skill_bridge.py` | **Test** | `test_scan_finds_real_skills` 加 `pytest.skip` 條件 |

**Production 修改：3 個檔案（2 個功能性 fix + 1 個 deprecated API fix）**
**Test 修改：4 個檔案（全部是測試債清理，非 production 邏輯改動）**

---

## 關鍵觀察：這次的 bug 性質

這 16 個失敗測試的**根本原因只有一個**：
> **v3 架構重構做得很徹底，但測試程式碼的更新沒有跟上。**

具體說：

- D1 決策刪除了 `_llm_score`，但 test_checker.py / test_orchestrator.py 還在 patch 它
- D23 決策讓 loop.py 從 `run()` 變成 `run_verification()`，但 test_orchestrator.py 還在 import `run`
- executor registry 擴充時沒有把新 executor 加進 `_BUILTIN_EXECUTORS`（這個是 production bug）
- `/models` 端點格式改了，測試沒更新

這說明一個工程實踐問題：**重構決策應該和測試更新一起落地，不可分批。**
測試是活的規格文件，落後的測試比沒有測試更危險——它讓 CI 失去可信度。

見 [DECISIONS.md](DECISIONS.md) D24、D25 節記錄決策。

---

## 驗證

修復完成後執行：

```bash
pytest tests/ -q
# 248 passed, 1 skipped, 0 failed in ~70s
```

1 skipped = `test_scan_finds_real_skills`（本機環境依賴，正確行為）。
