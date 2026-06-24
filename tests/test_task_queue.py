"""
測試 orchestrator/task_queue.py

覆蓋項目：
  1. push → pending 狀態、attempt_count=0
  2. 純 FIFO：三個任務依 created_at 升序取出
  3. next_pending 取出時 status=running、attempt_count+1
  4. update_status：合法狀態轉換（running→passed / escalated / dead）
  5. update_status：非法狀態 → ValueError
  6. 毒任務（dead）永不被 next_pending 撿到
  7. queue_depth 計數正確
  8. list_triage 查詢 escalated / dead
  9. get_task 回傳完整 dict；不存在回傳 None
 10. 佇列空時 next_pending 回傳 None

每個測試使用獨立的臨時 DB（AGENTOS_TASK_QUEUE_DB_PATH env var），互不干擾。
"""
import os
import time
import pytest
from pathlib import Path

from contracts.task_spec import TaskSpec


# ── fixture ──────────────────────────────────────────────────────────────────

def _make_spec(why: str = "test task") -> TaskSpec:
    return TaskSpec(
        why=why,
        io_example={"expected_output": "ok"},
        taste=[],
        boundaries=[],
        stop_on_metric="correctness",
        max_rounds=3,
    )


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """每個測試一個獨立的臨時 SQLite DB。"""
    db_path = tmp_path / "test_queue.db"
    monkeypatch.setenv("AGENTOS_TASK_QUEUE_DB_PATH", str(db_path))
    # 確保 task_queue 模組重新讀取 env（其 _db_path() 是 function，每次呼叫都查 env）
    from orchestrator import task_queue
    task_queue._SCHEMA_ENSURED = False  # 清除 cache，讓 ensure_schema 對新的 temp 路徑生效
    task_queue.ensure_schema()
    yield db_path


# ── tests ────────────────────────────────────────────────────────────────────

class TestPush:
    def test_push_returns_task_id(self, tmp_db):
        from orchestrator import task_queue
        spec = _make_spec()
        task_id = task_queue.push(spec)
        assert isinstance(task_id, str) and len(task_id) > 0

    def test_push_initial_status_pending(self, tmp_db):
        from orchestrator import task_queue
        spec = _make_spec()
        task_id = task_queue.push(spec)
        task = task_queue.get_task(task_id)
        assert task is not None
        assert task["status"] == "pending"
        assert task["attempt_count"] == 0

    def test_push_multiple_same_spec_creates_distinct_ids(self, tmp_db):
        from orchestrator import task_queue
        spec = _make_spec()
        ids = {task_queue.push(spec) for _ in range(5)}
        assert len(ids) == 5


class TestFIFO:
    def test_three_tasks_dequeued_in_created_at_order(self, tmp_db):
        """核心驗收：純 FIFO，斷言取出順序 = created_at 升序。"""
        from orchestrator import task_queue

        id1 = task_queue.push(_make_spec("first"))
        time.sleep(0.01)   # 確保 created_at 不同
        id2 = task_queue.push(_make_spec("second"))
        time.sleep(0.01)
        id3 = task_queue.push(_make_spec("third"))

        t1 = task_queue.next_pending()
        t2 = task_queue.next_pending()
        t3 = task_queue.next_pending()

        assert t1 is not None and t1["task_id"] == id1
        assert t2 is not None and t2["task_id"] == id2
        assert t3 is not None and t3["task_id"] == id3

    def test_empty_queue_returns_none(self, tmp_db):
        from orchestrator import task_queue
        result = task_queue.next_pending()
        assert result is None


class TestNextPending:
    def test_next_pending_sets_running_and_increments_attempt(self, tmp_db):
        from orchestrator import task_queue
        task_id = task_queue.push(_make_spec())
        task = task_queue.next_pending()
        assert task is not None
        assert task["task_id"] == task_id
        assert task["status"] == "running"
        assert task["attempt_count"] == 1

    def test_next_pending_increments_attempt_on_re_queue(self, tmp_db):
        """將 running 任務重設回 pending 後，再次取出 attempt_count 應為 2。"""
        from orchestrator import task_queue
        task_id = task_queue.push(_make_spec())
        # 第一次取出
        task_queue.next_pending()
        # 手動重設為 pending（模擬 runner 崩潰重啟場景）
        task_queue.update_status(task_id, "pending")
        # 第二次取出
        task = task_queue.next_pending()
        assert task is not None
        assert task["attempt_count"] == 2


class TestUpdateStatus:
    def test_update_to_passed(self, tmp_db):
        from orchestrator import task_queue
        task_id = task_queue.push(_make_spec())
        task_queue.next_pending()  # → running
        task_queue.update_status(task_id, "passed", score=8.5, feedback="great")
        task = task_queue.get_task(task_id)
        assert task["status"] == "passed"
        assert task["last_score"] == pytest.approx(8.5)
        assert task["last_feedback"] == "great"

    def test_update_to_escalated(self, tmp_db):
        from orchestrator import task_queue
        task_id = task_queue.push(_make_spec())
        task_queue.next_pending()
        task_queue.update_status(task_id, "escalated", score=3.0,
                                 notes={"reason": "max_rounds"})
        task = task_queue.get_task(task_id)
        assert task["status"] == "escalated"
        assert task["notes"]["reason"] == "max_rounds"

    def test_update_to_dead(self, tmp_db):
        from orchestrator import task_queue
        task_id = task_queue.push(_make_spec())
        task_queue.next_pending()
        task_queue.update_status(task_id, "dead", score=0.0)
        task = task_queue.get_task(task_id)
        assert task["status"] == "dead"

    def test_update_invalid_status_raises(self, tmp_db):
        from orchestrator import task_queue
        task_id = task_queue.push(_make_spec())
        with pytest.raises(ValueError, match="invalid status"):
            task_queue.update_status(task_id, "zombie")


class TestDeadTaskNotRescued:
    def test_dead_task_never_returned_by_next_pending(self, tmp_db):
        """毒任務驗收：dead 任務不得再被 next_pending 撿到。"""
        from orchestrator import task_queue
        # 放兩個任務
        dead_id = task_queue.push(_make_spec("poison task"))
        good_id = task_queue.push(_make_spec("good task"))

        # 取出第一個，標為 dead
        first = task_queue.next_pending()
        assert first["task_id"] == dead_id
        task_queue.update_status(dead_id, "dead", score=0.0)

        # 下一個取出應是 good task，而非 dead 的那個
        second = task_queue.next_pending()
        assert second is not None
        assert second["task_id"] == good_id

        # 再取一次：佇列應為空（dead 不回收）
        third = task_queue.next_pending()
        assert third is None

    def test_dead_task_depth_not_counted_in_pending(self, tmp_db):
        from orchestrator import task_queue
        task_id = task_queue.push(_make_spec())
        task_queue.next_pending()
        task_queue.update_status(task_id, "dead", score=0.0)
        assert task_queue.queue_depth("pending") == 0
        assert task_queue.queue_depth("dead") == 1


class TestQueueDepth:
    def test_depth_counts_correctly(self, tmp_db):
        from orchestrator import task_queue
        assert task_queue.queue_depth("pending") == 0
        task_queue.push(_make_spec())
        task_queue.push(_make_spec())
        assert task_queue.queue_depth("pending") == 2
        task = task_queue.next_pending()
        assert task_queue.queue_depth("pending") == 1
        assert task_queue.queue_depth("running") == 1


class TestListTriage:
    def test_list_triage_escalated(self, tmp_db):
        from orchestrator import task_queue
        id1 = task_queue.push(_make_spec("task a"))
        id2 = task_queue.push(_make_spec("task b"))
        task_queue.next_pending()
        task_queue.update_status(id1, "escalated", score=3.0)
        task_queue.next_pending()
        task_queue.update_status(id2, "escalated", score=4.0)

        triage = task_queue.list_triage("escalated")
        ids = {t["task_id"] for t in triage}
        assert id1 in ids and id2 in ids

    def test_list_triage_dead(self, tmp_db):
        from orchestrator import task_queue
        task_id = task_queue.push(_make_spec())
        task_queue.next_pending()
        task_queue.update_status(task_id, "dead", score=0.0)
        dead = task_queue.list_triage("dead")
        assert any(t["task_id"] == task_id for t in dead)

    def test_list_triage_invalid_status_raises(self, tmp_db):
        from orchestrator import task_queue
        with pytest.raises(ValueError, match="invalid status"):
            task_queue.list_triage("zombie")


class TestGetTask:
    def test_get_task_nonexistent_returns_none(self, tmp_db):
        from orchestrator import task_queue
        assert task_queue.get_task("nonexistent-id") is None

    def test_get_task_returns_full_dict(self, tmp_db):
        from orchestrator import task_queue
        spec = _make_spec("full dict test")
        task_id = task_queue.push(spec, notes={"source": "test"})
        task = task_queue.get_task(task_id)
        assert task is not None
        assert task["task_id"] == task_id
        assert "spec_json" in task
        assert task["notes"]["source"] == "test"
        assert task["status"] == "pending"
