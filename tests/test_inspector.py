"""測試 orchestrator/inspector.py — A 巡檢器

覆蓋項目（對應任務說明第七點 + Ryan 加的去重語意）：
  1. pytest 全綠 → 不產任何任務，回報 total_failed=0
  2. pytest 有 3 個紅 → 產 3 個任務，source="A"、fingerprint 正確
  3. 【去重核心】同一個失敗，連跑兩次 run_inspection → 第二次跳過，佇列只有 1 個任務
  4. 已有 running 任務 → 跳過不產
  5. 產的任務是合法 TaskSpec（能被 runner 取出的格式）
  6. pytest timeout → 不崩潰，回報 timed_out=True
  7. 【Ryan 加】dead 不在去重範圍 → fingerprint 曾 dead，下次允許重新產

所有測試使用 mock 的 pytest 輸出（不真跑整個 tests/，可控、快）。
DB 隔離：每個測試獨立 tmp SQLite（monkeypatch env var）。
"""
import sys
import json
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from contracts.task_spec import TaskSpec


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_pytest_stdout(failed: list[str], passed_count: int = 10) -> str:
    """組一個 pytest -v --tb=no 風格的輸出字串。

    failed: 失敗測試名清單，格式 "tests/test_foo.py::test_bar"
    """
    lines = []
    for name in failed:
        lines.append(f"{name} FAILED")
    for i in range(passed_count):
        lines.append(f"tests/test_dummy.py::test_pass_{i} PASSED")
    if failed:
        lines.append(f"{len(failed)} failed, {passed_count} passed")
    else:
        lines.append(f"{passed_count} passed")
    return "\n".join(lines)


def _all_green_stdout() -> str:
    return "10 passed, 1 skipped\n"


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """每個測試一個獨立的臨時 SQLite DB。"""
    db_path = tmp_path / "test_inspector.db"
    monkeypatch.setenv("AGENTOS_TASK_QUEUE_DB_PATH", str(db_path))
    from orchestrator import task_queue
    task_queue.ensure_schema()
    yield db_path


def _mock_run_pytest(stdout: str, exit_code: int = 0):
    """回傳一個假的 _run_pytest 結果 dict（不真跑 subprocess）。"""
    return {
        "stdout": stdout,
        "exit_code": exit_code,
        "timed_out": False,
        "error": None,
    }


# ── tests ─────────────────────────────────────────────────────────────────────

class TestInspectionAllGreen:
    """驗收點 1：pytest 全綠 → 不產任何任務。"""

    def test_all_green_pushes_nothing(self, tmp_db):
        from orchestrator.inspector import run_inspection

        with patch("orchestrator.inspector._run_pytest",
                   return_value=_mock_run_pytest(_all_green_stdout(), exit_code=0)):
            result = run_inspection()

        assert result["ok"] is True
        assert result["total_failed"] == 0
        assert result["pushed"] == 0
        assert result["task_ids"] == []

    def test_all_green_queue_stays_empty(self, tmp_db):
        from orchestrator.inspector import run_inspection
        from orchestrator import task_queue

        with patch("orchestrator.inspector._run_pytest",
                   return_value=_mock_run_pytest(_all_green_stdout(), exit_code=0)):
            run_inspection()

        assert task_queue.queue_depth("pending") == 0


class TestInspectionWithFailures:
    """驗收點 2：pytest 有 N 個紅 → 產 N 個任務，source='A'、fingerprint 正確。"""

    def test_three_failures_produce_three_tasks(self, tmp_db):
        from orchestrator.inspector import run_inspection

        fps = [
            "tests/test_foo.py::test_alpha",
            "tests/test_bar.py::test_beta",
            "tests/test_baz.py::TestClass::test_gamma",
        ]
        stdout = _make_pytest_stdout(fps)

        with patch("orchestrator.inspector._run_pytest",
                   return_value=_mock_run_pytest(stdout, exit_code=1)):
            result = run_inspection()

        assert result["total_failed"] == 3
        assert result["pushed"] == 3
        assert result["skipped_duplicate"] == 0
        assert len(result["task_ids"]) == 3
        assert sorted(result["fingerprints_pushed"]) == sorted(fps)

    def test_tasks_have_source_A(self, tmp_db):
        from orchestrator.inspector import run_inspection
        from orchestrator import task_queue

        fp = "tests/test_foo.py::test_x"
        stdout = _make_pytest_stdout([fp])

        with patch("orchestrator.inspector._run_pytest",
                   return_value=_mock_run_pytest(stdout, exit_code=1)):
            result = run_inspection()

        task_id = result["task_ids"][0]
        task = task_queue.get_task(task_id)
        assert task is not None
        assert task["notes"]["source"] == "A"

    def test_tasks_have_correct_fingerprint_in_notes(self, tmp_db):
        from orchestrator.inspector import run_inspection
        from orchestrator import task_queue

        fp = "tests/test_foo.py::test_check_something"
        stdout = _make_pytest_stdout([fp])

        with patch("orchestrator.inspector._run_pytest",
                   return_value=_mock_run_pytest(stdout, exit_code=1)):
            result = run_inspection()

        task_id = result["task_ids"][0]
        task = task_queue.get_task(task_id)
        assert task["notes"]["fingerprint"] == fp


class TestDeduplication:
    """驗收點 3 + 4：去重核心——同一個 fingerprint 不重複產任務。"""

    def test_second_inspection_skips_existing_pending(self, tmp_db):
        """連跑兩次 run_inspection → 第二次跳過，佇列只有 1 個 pending 任務。"""
        from orchestrator.inspector import run_inspection
        from orchestrator import task_queue

        fp = "tests/test_foo.py::test_repeat"
        stdout = _make_pytest_stdout([fp])
        mock_result = _mock_run_pytest(stdout, exit_code=1)

        with patch("orchestrator.inspector._run_pytest", return_value=mock_result):
            result1 = run_inspection()
        with patch("orchestrator.inspector._run_pytest", return_value=mock_result):
            result2 = run_inspection()

        # 第一次產了 1 個任務
        assert result1["pushed"] == 1
        assert result1["skipped_duplicate"] == 0
        # 第二次跳過，不重產
        assert result2["pushed"] == 0
        assert result2["skipped_duplicate"] == 1
        assert fp in result2["fingerprints_skipped"]
        # 佇列裡只有 1 個任務
        assert task_queue.queue_depth("pending") == 1

    def test_skips_when_running_task_exists(self, tmp_db):
        """已有 running 任務 → 巡檢時跳過不產。"""
        from orchestrator.inspector import run_inspection
        from orchestrator import task_queue

        fp = "tests/test_foo.py::test_in_progress"
        stdout = _make_pytest_stdout([fp])

        # 先產一個任務，再把它改成 running
        with patch("orchestrator.inspector._run_pytest",
                   return_value=_mock_run_pytest(stdout, exit_code=1)):
            result1 = run_inspection()

        task_id = result1["task_ids"][0]
        # 模擬 runner 把它取出（status → running）
        task_queue.update_status(task_id, "running", score=None, feedback=None)

        # 再跑一次巡檢
        with patch("orchestrator.inspector._run_pytest",
                   return_value=_mock_run_pytest(stdout, exit_code=1)):
            result2 = run_inspection()

        assert result2["pushed"] == 0
        assert result2["skipped_duplicate"] == 1

    def test_skips_when_escalated_task_exists(self, tmp_db):
        """已有 escalated 任務 → 跳過（由人手動重試，機器不自動重試）。"""
        from orchestrator.inspector import run_inspection
        from orchestrator import task_queue

        fp = "tests/test_foo.py::test_hard_to_fix"
        stdout = _make_pytest_stdout([fp])

        with patch("orchestrator.inspector._run_pytest",
                   return_value=_mock_run_pytest(stdout, exit_code=1)):
            result1 = run_inspection()

        task_id = result1["task_ids"][0]
        task_queue.update_status(task_id, "escalated", score=3.0, feedback="no progress")

        with patch("orchestrator.inspector._run_pytest",
                   return_value=_mock_run_pytest(stdout, exit_code=1)):
            result2 = run_inspection()

        assert result2["pushed"] == 0
        assert result2["skipped_duplicate"] == 1


class TestDeadNotInDedup:
    """驗收點 7（Ryan 加）：dead 不在去重範圍，環境修好後允許重新產任務。"""

    def test_dead_task_allows_new_push(self, tmp_db):
        """fingerprint 曾 dead，下次巡檢時允許重新產（不被去重跳過）。"""
        from orchestrator.inspector import run_inspection
        from orchestrator import task_queue

        fp = "tests/test_env.py::test_network_dependent"
        stdout = _make_pytest_stdout([fp])

        # 第一次巡檢 → 產任務
        with patch("orchestrator.inspector._run_pytest",
                   return_value=_mock_run_pytest(stdout, exit_code=1)):
            result1 = run_inspection()

        assert result1["pushed"] == 1
        task_id = result1["task_ids"][0]

        # 模擬 runner 跑完，判定為 dead（score=0.0，環境錯）
        task_queue.update_status(task_id, "dead", score=0.0, feedback="env error")

        # 第二次巡檢：dead 不在去重範圍 → 應該重新產任務
        with patch("orchestrator.inspector._run_pytest",
                   return_value=_mock_run_pytest(stdout, exit_code=1)):
            result2 = run_inspection()

        # 關鍵斷言：dead 不擋路，第二次也能產
        assert result2["pushed"] == 1, (
            f"dead 不在去重範圍，應允許重新產任務，但 pushed={result2['pushed']}, "
            f"skipped={result2['skipped_duplicate']}"
        )
        assert result2["skipped_duplicate"] == 0


class TestValidTaskSpec:
    """驗收點 5：產的任務是合法 TaskSpec。"""

    def test_pushed_task_has_valid_spec(self, tmp_db):
        from orchestrator.inspector import run_inspection
        from orchestrator import task_queue

        fp = "tests/test_spec.py::test_validate_me"
        stdout = _make_pytest_stdout([fp])

        with patch("orchestrator.inspector._run_pytest",
                   return_value=_mock_run_pytest(stdout, exit_code=1)):
            result = run_inspection()

        task_id = result["task_ids"][0]
        task = task_queue.get_task(task_id)
        assert task is not None

        # spec_json 應能反序列化成合法 TaskSpec
        spec_dict = json.loads(task["spec_json"])
        spec = TaskSpec(**spec_dict)          # 若非法 Pydantic 會 raise

        assert fp in spec.why
        assert "expected_output" in spec.io_example
        assert spec.max_rounds == 3
        assert len(spec.taste) > 0
        assert len(spec.boundaries) >= 3      # 至少三條邊界條件

    def test_spec_boundaries_include_no_unrelated_files(self, tmp_db):
        """boundaries 含「不可修改與此測試無關的其他檔案」（Ryan 微調）。"""
        from orchestrator.inspector import run_inspection
        from orchestrator import task_queue

        fp = "tests/test_spec.py::test_boundary_check"
        stdout = _make_pytest_stdout([fp])

        with patch("orchestrator.inspector._run_pytest",
                   return_value=_mock_run_pytest(stdout, exit_code=1)):
            result = run_inspection()

        task = task_queue.get_task(result["task_ids"][0])
        spec_dict = json.loads(task["spec_json"])

        boundaries_text = " ".join(spec_dict["boundaries"])
        assert "無關" in boundaries_text or "unrelated" in boundaries_text.lower(), (
            "boundaries 應包含「不可修改與此測試無關的其他檔案」"
        )


class TestPytestTimeout:
    """驗收點 6：pytest timeout → 不崩潰，回報 timed_out=True，不產任務。"""

    def test_timeout_returns_error_state(self, tmp_db):
        from orchestrator.inspector import run_inspection

        timeout_result = {
            "stdout": "[inspector] pytest timed out after 120s",
            "exit_code": -1,
            "timed_out": True,
            "error": "timeout after 120s",
        }

        with patch("orchestrator.inspector._run_pytest", return_value=timeout_result):
            result = run_inspection()

        assert result["ok"] is False
        assert result["timed_out"] is True
        assert result["pushed"] == 0
        assert result["task_ids"] == []

    def test_timeout_does_not_raise(self, tmp_db):
        """timeout 時不拋例外，正常回傳。"""
        from orchestrator.inspector import run_inspection

        timeout_result = {
            "stdout": "",
            "exit_code": -1,
            "timed_out": True,
            "error": "timeout after 120s",
        }

        with patch("orchestrator.inspector._run_pytest", return_value=timeout_result):
            try:
                result = run_inspection()
            except Exception as exc:
                pytest.fail(f"run_inspection raised exception on timeout: {exc}")

        assert result is not None
