"""tests/test_heartbeat.py — heartbeat.run_once() 五個分支驗收

每個分支都用 mock 隔離 inspector 和 runner，不跑真實 pytest / LLM。

五個分支：
  1. budget_already_exhausted    — 預檢即發現耗盡，inspector 和 run_loop 都不呼叫
  2. all_green_no_tasks          — pytest 全綠，佇列空，run_loop 什麼都沒跑
  3. inspector_pushes_tasks      — inspector 找到失敗，推任務，run_loop 處理
  4. budget_exhausted_after_loop — 預檢通過，run_loop 跑完後回報 budget_exhausted=True
  5. inspector_timeout           — inspector timed_out=True，仍照常呼叫 run_loop

驗收標準（Ryan 規格）：
  - 分支 1：inspection=None, loop=None, budget_exhausted_pre=True
  - 分支 2：inspection.pushed=0, loop.processed=0, budget_exhausted_post=False
  - 分支 3：inspection.pushed > 0, loop.processed > 0
  - 分支 4：budget_exhausted_post=True（run_loop 回報）
  - 分支 5：inspection.timed_out=True, loop 仍被呼叫（不因 inspector 失敗就跳過）
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator import heartbeat

# ── helper：標準 run_loop 回傳結構 ───────────────────────────────────────────

def _loop_result(
    processed=0, passed=0, escalated=0, dead=0,
    spent_usd=0.0, budget_exhausted=False,
) -> dict:
    return {
        "processed": processed,
        "passed": passed,
        "escalated": escalated,
        "dead": dead,
        "spent_usd": spent_usd,
        "budget_exhausted": budget_exhausted,
    }


def _inspection_result(
    ok=True, timed_out=False, error=None, exit_code=0,
    total_failed=0, pushed=0, skipped_duplicate=0,
    task_ids=None, fingerprints_pushed=None, fingerprints_skipped=None,
) -> dict:
    return {
        "ok": ok,
        "timed_out": timed_out,
        "error": error,
        "exit_code": exit_code,
        "total_failed": total_failed,
        "pushed": pushed,
        "skipped_duplicate": skipped_duplicate,
        "task_ids": task_ids or [],
        "fingerprints_pushed": fingerprints_pushed or [],
        "fingerprints_skipped": fingerprints_skipped or [],
    }


# ── 分支 1：預算在進門時已耗盡 ───────────────────────────────────────────────

class TestBudgetAlreadyExhausted:
    """預檢時 ledger_spent_today() >= budget → inspector 和 run_loop 都不呼叫。"""

    def test_returns_early_without_calling_inspector_or_runner(self):
        """分支 1 核心：門口保全擋住，inspection=None, loop=None。"""
        with (
            patch("orchestrator.heartbeat.task_queue.ledger_spent_today", return_value=5.00),
            patch("orchestrator.heartbeat._inspector.run_inspection") as mock_inspect,
            patch("orchestrator.heartbeat.run_loop") as mock_loop,
        ):
            result = heartbeat.run_once(global_budget_usd=5.00, beat_n=1)

        assert result["budget_exhausted_pre"] is True
        assert result["inspection"] is None
        assert result["loop"] is None
        mock_inspect.assert_not_called()
        mock_loop.assert_not_called()

    def test_spent_before_reflects_ledger_value(self):
        """budget_exhausted_pre 時，spent_before 要記錄實際讀到的值。"""
        with (
            patch("orchestrator.heartbeat.task_queue.ledger_spent_today", return_value=6.50),
            patch("orchestrator.heartbeat._inspector.run_inspection"),
            patch("orchestrator.heartbeat.run_loop"),
        ):
            result = heartbeat.run_once(global_budget_usd=5.00, beat_n=0)

        assert result["spent_before"] == pytest.approx(6.50)
        assert result["budget_exhausted_pre"] is True

    def test_budget_exactly_equal_is_exhausted(self):
        """花費 == 上限（非嚴格小於），也算耗盡。"""
        with (
            patch("orchestrator.heartbeat.task_queue.ledger_spent_today", return_value=5.00),
            patch("orchestrator.heartbeat._inspector.run_inspection") as mock_inspect,
            patch("orchestrator.heartbeat.run_loop") as mock_loop,
        ):
            result = heartbeat.run_once(global_budget_usd=5.00)

        assert result["budget_exhausted_pre"] is True
        mock_inspect.assert_not_called()
        mock_loop.assert_not_called()


# ── 分支 2：全綠，佇列空 ─────────────────────────────────────────────────────

class TestAllGreenNoTasks:
    """pytest 全綠，inspector 推 0 任務，run_loop 跑 0 個 task。"""

    def test_full_beat_with_nothing_to_do(self):
        """分支 2 核心：inspection.pushed=0, loop.processed=0。"""
        with (
            patch("orchestrator.heartbeat.task_queue.ledger_spent_today", return_value=0.0),
            patch("orchestrator.heartbeat._inspector.run_inspection",
                  return_value=_inspection_result(ok=True, pushed=0)),
            patch("orchestrator.heartbeat.run_loop",
                  return_value=_loop_result(processed=0)),
        ):
            result = heartbeat.run_once(global_budget_usd=5.00, beat_n=2)

        assert result["budget_exhausted_pre"] is False
        assert result["budget_exhausted_post"] is False
        assert result["inspection"]["pushed"] == 0
        assert result["inspection"]["ok"] is True
        assert result["loop"]["processed"] == 0

    def test_beat_n_is_recorded(self):
        """beat_n 要正確帶進回傳 dict。"""
        with (
            patch("orchestrator.heartbeat.task_queue.ledger_spent_today", return_value=0.0),
            patch("orchestrator.heartbeat._inspector.run_inspection",
                  return_value=_inspection_result()),
            patch("orchestrator.heartbeat.run_loop",
                  return_value=_loop_result()),
        ):
            result = heartbeat.run_once(global_budget_usd=5.00, beat_n=42)

        assert result["beat_n"] == 42

    def test_run_loop_receives_same_budget(self):
        """heartbeat 傳給 run_loop 的 global_budget_usd 要和自己用的一致。"""
        mock_loop = MagicMock(return_value=_loop_result())
        with (
            patch("orchestrator.heartbeat.task_queue.ledger_spent_today", return_value=0.0),
            patch("orchestrator.heartbeat._inspector.run_inspection",
                  return_value=_inspection_result()),
            patch("orchestrator.heartbeat.run_loop", mock_loop),
        ):
            heartbeat.run_once(global_budget_usd=3.50, beat_n=0)

        mock_loop.assert_called_once()
        call_kwargs = mock_loop.call_args.kwargs
        assert call_kwargs["global_budget_usd"] == pytest.approx(3.50)


# ── 分支 3：inspector 找到失敗，run_loop 處理任務 ────────────────────────────

class TestInspectorPushesTasks:
    """inspector 推了 2 個任務，run_loop 處理並 passed。"""

    def test_inspection_and_loop_both_called(self):
        """分支 3 核心：inspection.pushed=2, loop.processed=2。"""
        with (
            patch("orchestrator.heartbeat.task_queue.ledger_spent_today", return_value=0.20),
            patch("orchestrator.heartbeat._inspector.run_inspection",
                  return_value=_inspection_result(
                      ok=False, total_failed=2, pushed=2,
                      task_ids=["t-aaa", "t-bbb"],
                      fingerprints_pushed=["tests/a.py::test_x", "tests/b.py::test_y"],
                  )),
            patch("orchestrator.heartbeat.run_loop",
                  return_value=_loop_result(processed=2, passed=2, spent_usd=0.05)),
        ):
            result = heartbeat.run_once(global_budget_usd=5.00, beat_n=3)

        assert result["budget_exhausted_pre"] is False
        assert result["inspection"]["pushed"] == 2
        assert result["inspection"]["total_failed"] == 2
        assert result["loop"]["processed"] == 2
        assert result["loop"]["passed"] == 2
        assert result["budget_exhausted_post"] is False

    def test_inspection_result_fully_preserved(self):
        """run_once 不裁剪 inspector 回傳，完整保留在 result['inspection']。"""
        insp = _inspection_result(
            ok=False, total_failed=1, pushed=1,
            task_ids=["t-xyz"],
            fingerprints_pushed=["tests/c.py::test_z"],
        )
        with (
            patch("orchestrator.heartbeat.task_queue.ledger_spent_today", return_value=0.0),
            patch("orchestrator.heartbeat._inspector.run_inspection", return_value=insp),
            patch("orchestrator.heartbeat.run_loop", return_value=_loop_result()),
        ):
            result = heartbeat.run_once(global_budget_usd=5.00)

        assert result["inspection"] == insp


# ── 分支 4：run_loop 跑完後油表耗盡 ──────────────────────────────────────────

class TestBudgetExhaustedAfterLoop:
    """預檢通過，run_loop 跑完後回報 budget_exhausted=True。"""

    def test_budget_exhausted_post_true(self):
        """分支 4 核心：budget_exhausted_post=True，且 inspection 和 loop 都有執行。"""
        with (
            # 預檢時還有餘裕（4.95）
            patch("orchestrator.heartbeat.task_queue.ledger_spent_today", return_value=4.95),
            patch("orchestrator.heartbeat._inspector.run_inspection",
                  return_value=_inspection_result(pushed=1, total_failed=1)),
            patch("orchestrator.heartbeat.run_loop",
                  return_value=_loop_result(processed=1, spent_usd=0.06,
                                            budget_exhausted=True)),
        ):
            result = heartbeat.run_once(global_budget_usd=5.00, beat_n=7)

        assert result["budget_exhausted_pre"] is False   # 預檢時沒耗盡
        assert result["budget_exhausted_post"] is True   # run_loop 後耗盡
        assert result["inspection"] is not None          # inspector 有跑
        assert result["loop"] is not None                # run_loop 有跑

    def test_loop_result_fully_preserved(self):
        """run_once 不裁剪 run_loop 回傳，完整保留在 result['loop']。"""
        loop_r = _loop_result(processed=3, passed=2, escalated=1, spent_usd=4.99,
                              budget_exhausted=True)
        with (
            patch("orchestrator.heartbeat.task_queue.ledger_spent_today", return_value=0.01),
            patch("orchestrator.heartbeat._inspector.run_inspection",
                  return_value=_inspection_result()),
            patch("orchestrator.heartbeat.run_loop", return_value=loop_r),
        ):
            result = heartbeat.run_once(global_budget_usd=5.00)

        assert result["loop"] == loop_r


# ── 分支 5：inspector 超時，run_loop 仍被呼叫 ────────────────────────────────

class TestInspectorTimeout:
    """inspector timed_out=True 時，run_loop 仍然被呼叫（佇列裡可能還有舊任務）。"""

    def test_run_loop_still_called_after_inspector_timeout(self):
        """分支 5 核心：inspection.timed_out=True，run_loop 仍執行。"""
        mock_loop = MagicMock(return_value=_loop_result())
        with (
            patch("orchestrator.heartbeat.task_queue.ledger_spent_today", return_value=0.0),
            patch("orchestrator.heartbeat._inspector.run_inspection",
                  return_value=_inspection_result(
                      ok=False, timed_out=True, error="timeout after 120s", exit_code=-1,
                  )),
            patch("orchestrator.heartbeat.run_loop", mock_loop),
        ):
            result = heartbeat.run_once(global_budget_usd=5.00, beat_n=5)

        assert result["inspection"]["timed_out"] is True
        mock_loop.assert_called_once()   # ← 關鍵：inspector 超時不跳過 run_loop

    def test_inspection_error_does_not_skip_loop(self):
        """inspector error（非 timeout）時，run_loop 仍執行。"""
        mock_loop = MagicMock(return_value=_loop_result())
        with (
            patch("orchestrator.heartbeat.task_queue.ledger_spent_today", return_value=0.0),
            patch("orchestrator.heartbeat._inspector.run_inspection",
                  return_value=_inspection_result(
                      ok=False, error="OSError: permission denied", exit_code=-1,
                  )),
            patch("orchestrator.heartbeat.run_loop", mock_loop),
        ):
            result = heartbeat.run_once(global_budget_usd=5.00)

        assert result["inspection"]["error"] is not None
        mock_loop.assert_called_once()
