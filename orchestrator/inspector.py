"""AgentOS A 巡檢器 — 本地 pytest 自我巡檢

職責：跑本地 tests/ 一次，找出失敗的測試，去重後產任務丟進佇列（source="A"）。
它只負責「巡檢一次」，不含排程/cron（那是 Trigger 那一棒的工作）。

核心流程：
  1. subprocess 跑 pytest tests/ -v（跑整個測試目錄）
  2. 解析輸出，抓出所有失敗的測試名（格式：tests/xxx.py::test_yyy）
  3. 對每個失敗：find_active_by_fingerprint → 已有 pending/running/escalated → 跳過
  4. 沒重複 → 組 TaskSpec → push(source="A", fingerprint=...)
  5. 回傳這次巡檢統計 dict

去重語意（Ryan 裁決，2026-06-22）：
  - 去重範圍：pending / running / escalated
  - passed：已修好，允許重新產（若又紅代表新回歸）
  - dead：環境錯，環境修好後允許重新產（避免偶發環境抖動永久封殺 fingerprint）
  - escalated：程式碼問題，交人後由人手動重試，機器不自動重試

設計限制：
  - 不改 checker / decision_log / safety / clarify / loop / runner 核心
  - task_queue 只呼叫既有公開函式 + find_active_by_fingerprint（唯讀）
  - 絕不上 Postgres/Redis/Docker
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from contracts.task_spec import TaskSpec
from orchestrator import task_queue

# ── 常數 ─────────────────────────────────────────────────────────────────────

PYTEST_TIMEOUT: int = 120          # 整個 tests/ 比單檔久，給兩倍時間
STDOUT_MAX: int = 8000             # 保留的 pytest 輸出上限（字元）
TESTS_DIR: str = "tests"           # 預設跑的目錄，可被 run_inspection 覆蓋
TASK_MAX_ROUNDS: int = 3           # A 自動產任務的 max_rounds（修測試比生 code 容易）

# 去抖：連續幾次都紅才產任務（防 flaky test 浪費配額）
DEBOUNCE_THRESHOLD: int = 2
_DEBOUNCE_COUNTER: dict[str, int] = {}  # fingerprint → consecutive_failures

# 解析 pytest「short test summary info」裡的失敗測試名。
# 格式：FAILED tests/test_foo.py::test_bar  （FAILED 在前，路徑在後）
# 這行在 -q / normal / -v 各模式的 summary 區都會出現，不依賴 verbosity。
# 舊版假設 "<path> FAILED"（-v 的 per-test 行），但命令的 -q 抵消了 -v，
# 真實輸出根本沒有那種行 → regex 永遠不命中 → inspector 偵測形同 no-op。
_FAILED_LINE_RE = re.compile(
    r'^FAILED\s+(\S+\.py::\S+)',
    re.MULTILINE,
)


# ── pytest runner ─────────────────────────────────────────────────────────────

def _run_pytest(tests_dir: str, timeout: int = PYTEST_TIMEOUT) -> dict[str, Any]:
    """跑 pytest <tests_dir>，回傳 {stdout, exit_code, timed_out, error}。

    永不拋例外，所有錯誤都包進回傳 dict。
    解析靠「short test summary info」的 `FAILED <path>::<test>` 行：
      -rf  ：強制輸出 failed 的 short summary（解析來源，不依賴 verbosity）。
      --tb=no：不要 traceback，減少輸出雜訊（失敗名解析不需要 traceback）。
      -q   ：壓掉 per-test 雜訊；summary 仍會印 FAILED 行。
    （舊版用 `-v ... -q` 自相矛盾——-q 抵消 -v，輸出回 normal，
      害得只配 -v 格式的 regex 永遠不命中。）
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", tests_dir, "--tb=no", "-q", "-rf"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(Path(__file__).parent.parent),  # repo root
        )
        stdout = (proc.stdout + proc.stderr)[:STDOUT_MAX]
        return {
            "stdout": stdout,
            "exit_code": proc.returncode,
            "timed_out": False,
            "error": None,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": f"[inspector] pytest timed out after {timeout}s",
            "exit_code": -1,
            "timed_out": True,
            "error": f"timeout after {timeout}s",
        }
    except Exception as exc:
        return {
            "stdout": str(exc)[:STDOUT_MAX],
            "exit_code": -1,
            "timed_out": False,
            "error": str(exc),
        }


# ── 失敗測試解析 ──────────────────────────────────────────────────────────────

def _parse_failed_tests(stdout: str) -> list[str]:
    """從 pytest -v 輸出中提取所有失敗的測試名。

    回傳去重後的清單（保留原始順序）。
    """
    found = _FAILED_LINE_RE.findall(stdout)
    # 去重（同一個測試不會出現兩次，但防禦性去重保持清單唯一）
    seen: set[str] = set()
    result: list[str] = []
    for name in found:
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


# ── TaskSpec 組裝 ─────────────────────────────────────────────────────────────

def _build_task_spec(fingerprint: str) -> TaskSpec:
    """為一個失敗測試組合 TaskSpec。

    填法裁決（Ryan，2026-06-22）：
    - why：清楚說明這是修復任務，包含 fingerprint
    - io_example.expected_output：pytest 該測試通過（exit code 0）
    - taste：限定改動範圍、確保其他測試不破
    - boundaries：四條紅線（不刪/skip 測試、不改斷言、不改無關檔案）
    - max_rounds=3：修測試比生 code 容易，3 輪省油表
    """
    return TaskSpec(
        why=f"修復失敗測試：{fingerprint}",
        io_example={
            "input": fingerprint,
            "expected_output": f"pytest {fingerprint} 通過（exit code 0）",
        },
        taste=[
            "只修復導致此測試失敗的程式碼，不要改動其他測試",
            "確認修改後整個 tests/ 目錄的其他測試仍然通過",
        ],
        boundaries=[
            "不可刪除或跳過（skip）這個測試",
            "不可修改測試本身的斷言邏輯",
            "不可修改與此測試無關的其他檔案",
        ],
        stop_on_metric="pytest 該測試 exit code 0",
        max_rounds=TASK_MAX_ROUNDS,
        executor="litellm",
    )


# ── 公開介面 ──────────────────────────────────────────────────────────────────

def run_inspection(
    *,
    tests_dir: str = TESTS_DIR,
    pytest_timeout: int = PYTEST_TIMEOUT,
) -> dict[str, Any]:
    """執行一次本地 pytest 自我巡檢。

    1. 跑 pytest <tests_dir> -v
    2. 解析失敗測試名
    3. 去重（pending/running/escalated 已有 → 跳過）
    4. 對未重複的失敗產任務（source="A"，notes 含 fingerprint）
    5. 回傳統計 dict

    回傳格式：
    {
        "ok": bool,               # pytest 跑完且全綠（或沒有失敗被處理）
        "timed_out": bool,
        "error": str | None,
        "exit_code": int,
        "total_failed": int,      # pytest 回報的失敗數
        "pushed": int,            # 本次實際產了幾個任務
        "skipped_duplicate": int, # 跳過了幾個（已有 pending/running/escalated）
        "task_ids": list[str],    # 本次產的 task_id 清單
        "fingerprints_pushed": list[str],
        "fingerprints_skipped": list[str],
    }
    """
    # 確保 schema 存在（測試環境用 tmp_db，生產環境在 data/）
    task_queue.ensure_schema()

    # ── 1. 跑 pytest ──────────────────────────────────────────────────────────
    pytest_result = _run_pytest(tests_dir, timeout=pytest_timeout)

    # timeout 或系統錯誤：早回，不產任務
    if pytest_result["timed_out"] or pytest_result["error"]:
        return {
            "ok": False,
            "timed_out": pytest_result["timed_out"],
            "error": pytest_result["error"],
            "exit_code": pytest_result["exit_code"],
            "total_failed": 0,
            "pushed": 0,
            "skipped_duplicate": 0,
            "task_ids": [],
            "fingerprints_pushed": [],
            "fingerprints_skipped": [],
        }

    # ── 2. 解析失敗測試名 ──────────────────────────────────────────────────────
    failed_tests = _parse_failed_tests(pytest_result["stdout"])

    # 清理去抖 counter：本次沒出現的 fingerprint 不再連續（全綠／部分紅都適用）
    for fp in list(_DEBOUNCE_COUNTER.keys()):
        if fp not in failed_tests:
            del _DEBOUNCE_COUNTER[fp]

    # 全綠：exit_code == 0，不產任務
    if not failed_tests:
        return {
            "ok": pytest_result["exit_code"] == 0,
            "timed_out": False,
            "error": None,
            "exit_code": pytest_result["exit_code"],
            "total_failed": 0,
            "pushed": 0,
            "skipped_duplicate": 0,
            "task_ids": [],
            "fingerprints_pushed": [],
            "fingerprints_skipped": [],
        }

    # ── 3 + 4. 去重 + 去抖 + 產任務 ──────────────────────────────────────────
    task_ids: list[str] = []
    pushed_fps: list[str] = []
    skipped_fps: list[str] = []
    debounced_fps: list[str] = []

    for fingerprint in failed_tests:
        existing = task_queue.find_active_by_fingerprint(fingerprint)
        if existing is not None:
            # 已有 pending / running / escalated → 跳過
            skipped_fps.append(fingerprint)
            continue

        # 去抖：檢查連續紅拍數
        count = _DEBOUNCE_COUNTER.get(fingerprint, 0) + 1
        _DEBOUNCE_COUNTER[fingerprint] = count

        if count < DEBOUNCE_THRESHOLD:
            # 還未達到 threshold，不產任務
            debounced_fps.append(fingerprint)
            continue

        # 達到 threshold → 產任務，清除 counter
        del _DEBOUNCE_COUNTER[fingerprint]
        spec = _build_task_spec(fingerprint)
        notes = {"source": "A", "fingerprint": fingerprint}
        task_id = task_queue.push(spec, notes=notes)
        task_ids.append(task_id)
        pushed_fps.append(fingerprint)

    # ── 5. 回傳統計 ──────────────────────────────────────────────────────────
    return {
        "ok": len(failed_tests) == 0,
        "timed_out": False,
        "error": None,
        "exit_code": pytest_result["exit_code"],
        "total_failed": len(failed_tests),
        "pushed": len(task_ids),
        "skipped_duplicate": len(skipped_fps),
        "debounced": len(debounced_fps),
        "task_ids": task_ids,
        "fingerprints_pushed": pushed_fps,
        "fingerprints_skipped": skipped_fps,
        "fingerprints_debounced": debounced_fps,
    }
