"""B 端點測試 — /queue/* 手動佇列 API

覆蓋項目（對應任務說明第六點 + Ryan 加的兩條）：
  1. POST /queue/push 成功 → 回 task_id，且任務真的在佇列裡
  2. POST /queue/push 帶非法 spec → 422
  3. GET /queue/status → 計數正確（先 push 幾個不同狀態的任務再查）
  4. GET /queue/list?status=pending → 只回 pending 的
  5. GET /queue/task/{id} 找不到 → 404
  6. spent_today_usd 正確反映 ledger
  7. GET /queue/status 空佇列 → 五個狀態 key 全在，值都是 0（補零語意）
  8. POST /queue/push source 非法值 → 422（不靜默竄改審計欄位）

每個測試使用獨立臨時 DB，透過 AGENTOS_TASK_QUEUE_DB_PATH env 隔離。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


# ── fixture ──────────────────────────────────────────────────────────────────

def _valid_spec(why: str = "implement feature X") -> dict:
    """最小合法 TaskSpec dict，POST /queue/push body 的 spec 欄位。"""
    return {
        "why": why,
        "io_example": {"expected_output": "working code"},
        "taste": [],
        "boundaries": [],
        "stop_on_metric": "correctness",
        "max_rounds": 3,
    }


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """每個測試一個獨立的臨時 SQLite DB，透過 env var 注入。"""
    db_path = tmp_path / "test_queue_api.db"
    monkeypatch.setenv("AGENTOS_TASK_QUEUE_DB_PATH", str(db_path))
    from orchestrator import task_queue
    task_queue._SCHEMA_ENSURED_FOR_PATH = ""
    task_queue.ensure_schema()
    yield db_path


# ── tests ─────────────────────────────────────────────────────────────────────

class TestQueuePushSuccess:
    """驗收點 1：POST /queue/push 成功 → 回 task_id，且任務真的在佇列裡。"""

    def test_push_returns_task_id(self, tmp_db):
        r = client.post("/queue/push", json={"spec": _valid_spec()})
        assert r.status_code == 200
        body = r.json()
        assert "task_id" in body
        assert isinstance(body["task_id"], str)
        assert len(body["task_id"]) > 0

    def test_push_task_actually_in_queue(self, tmp_db):
        """push 後用 get_task 驗證任務真的寫進佇列。"""
        r = client.post("/queue/push", json={"spec": _valid_spec("verify me")})
        assert r.status_code == 200
        task_id = r.json()["task_id"]

        # 用 /queue/task/{id} 端點驗，不直接查 DB（測端點，不測內部）
        detail = client.get(f"/queue/task/{task_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["task_id"] == task_id
        assert body["status"] == "pending"

    def test_push_source_stored_in_notes(self, tmp_db):
        """source='B' 要存進 notes.source。"""
        r = client.post("/queue/push", json={"source": "B", "spec": _valid_spec()})
        assert r.status_code == 200
        task_id = r.json()["task_id"]

        detail = client.get(f"/queue/task/{task_id}")
        assert detail.status_code == 200
        assert detail.json()["notes"]["source"] == "B"

    def test_push_default_source_is_B(self, tmp_db):
        """未傳 source → 預設 'B'。"""
        r = client.post("/queue/push", json={"spec": _valid_spec()})
        assert r.status_code == 200
        task_id = r.json()["task_id"]

        detail = client.get(f"/queue/task/{task_id}")
        assert detail.json()["notes"]["source"] == "B"

    def test_push_source_A_accepted(self, tmp_db):
        """source='A'（巡檢器）也是合法值。"""
        r = client.post("/queue/push", json={"source": "A", "spec": _valid_spec()})
        assert r.status_code == 200
        task_id = r.json()["task_id"]

        detail = client.get(f"/queue/task/{task_id}")
        assert detail.json()["notes"]["source"] == "A"


class TestQueuePushInvalidSpec:
    """驗收點 2：POST /queue/push 帶非法 spec → 422。"""

    def test_missing_why_returns_422(self, tmp_db):
        bad_spec = {
            "io_example": {"expected_output": "ok"},
            "taste": [],
            "boundaries": [],
        }
        r = client.post("/queue/push", json={"spec": bad_spec})
        assert r.status_code == 422

    def test_empty_why_returns_422(self, tmp_db):
        bad_spec = {
            "why": "   ",  # 全空白，TaskSpec validator 攔
            "io_example": {"expected_output": "ok"},
            "taste": [],
            "boundaries": [],
        }
        r = client.post("/queue/push", json={"spec": bad_spec})
        assert r.status_code == 422

    def test_missing_io_example_returns_422(self, tmp_db):
        bad_spec = {
            "why": "something",
            "taste": [],
            "boundaries": [],
        }
        r = client.post("/queue/push", json={"spec": bad_spec})
        assert r.status_code == 422

    def test_io_example_missing_expected_output_returns_422(self, tmp_db):
        bad_spec = {
            "why": "something",
            "io_example": {"input": "x"},  # 缺 expected_output
            "taste": [],
            "boundaries": [],
        }
        r = client.post("/queue/push", json={"spec": bad_spec})
        assert r.status_code == 422


class TestQueueSourceValidation:
    """驗收點 8（Ryan 加）：source 非法值 → 422，不靜默竄改審計欄位。"""

    def test_invalid_source_returns_422(self, tmp_db):
        r = client.post("/queue/push", json={"source": "X", "spec": _valid_spec()})
        assert r.status_code == 422

    def test_source_C_returns_422(self, tmp_db):
        r = client.post("/queue/push", json={"source": "C", "spec": _valid_spec()})
        assert r.status_code == 422

    def test_source_lowercase_b_returns_422(self, tmp_db):
        """大小寫敏感：'b' 不等於 'B'。"""
        r = client.post("/queue/push", json={"source": "b", "spec": _valid_spec()})
        assert r.status_code == 422


class TestQueueStatus:
    """驗收點 3：GET /queue/status → 計數正確。"""

    def test_status_empty_queue_all_zero(self, tmp_db):
        """驗收點 7（Ryan 加）：空佇列時五個狀態 key 全在，值都是 0。"""
        r = client.get("/queue/status")
        assert r.status_code == 200
        body = r.json()
        for key in ("pending", "running", "passed", "escalated", "dead"):
            assert key in body, f"key '{key}' missing from /queue/status"
            assert body[key] == 0, f"expected {key}=0, got {body[key]}"
        assert "spent_today_usd" in body

    def test_status_counts_reflect_pushed_tasks(self, tmp_db):
        """push 兩個 pending 後，pending 計數應為 2。"""
        client.post("/queue/push", json={"spec": _valid_spec("task A")})
        client.post("/queue/push", json={"spec": _valid_spec("task B")})

        r = client.get("/queue/status")
        assert r.status_code == 200
        body = r.json()
        assert body["pending"] == 2
        assert body["running"] == 0
        assert body["passed"] == 0

    def test_status_after_status_changes(self, tmp_db):
        """手動變更狀態後，計數要即時反映。"""
        from orchestrator import task_queue

        id1 = client.post("/queue/push", json={"spec": _valid_spec("t1")}).json()["task_id"]
        id2 = client.post("/queue/push", json={"spec": _valid_spec("t2")}).json()["task_id"]
        id3 = client.post("/queue/push", json={"spec": _valid_spec("t3")}).json()["task_id"]

        # 直接用 task_queue 改狀態，模擬 runner 跑完
        task_queue.update_status(id1, "passed", score=8.0, feedback="good")
        task_queue.update_status(id2, "escalated", score=3.0, feedback="stuck")
        # id3 保持 pending

        r = client.get("/queue/status")
        body = r.json()
        assert body["pending"] == 1
        assert body["passed"] == 1
        assert body["escalated"] == 1
        assert body["running"] == 0
        assert body["dead"] == 0

    def test_status_five_keys_always_present_with_partial_data(self, tmp_db):
        """即使只有 passed 任務，dead/running/pending/escalated 也要在（補零）。"""
        from orchestrator import task_queue

        task_id = client.post("/queue/push", json={"spec": _valid_spec()}).json()["task_id"]
        task_queue.update_status(task_id, "passed", score=9.0, feedback="done")

        r = client.get("/queue/status")
        body = r.json()
        for key in ("pending", "running", "passed", "escalated", "dead"):
            assert key in body


class TestQueueList:
    """驗收點 4：GET /queue/list?status=pending → 只回 pending 的。"""

    def test_list_pending_only(self, tmp_db):
        from orchestrator import task_queue

        id_p = client.post("/queue/push", json={"spec": _valid_spec("p")}).json()["task_id"]
        id_e = client.post("/queue/push", json={"spec": _valid_spec("e")}).json()["task_id"]
        task_queue.update_status(id_e, "escalated", score=2.0, feedback="stuck")

        r = client.get("/queue/list?status=pending")
        assert r.status_code == 200
        body = r.json()
        ids = [t["task_id"] for t in body["tasks"]]
        assert id_p in ids
        assert id_e not in ids
        assert all(t["status"] == "pending" for t in body["tasks"])

    def test_list_no_status_returns_all(self, tmp_db):
        from orchestrator import task_queue

        id1 = client.post("/queue/push", json={"spec": _valid_spec("t1")}).json()["task_id"]
        id2 = client.post("/queue/push", json={"spec": _valid_spec("t2")}).json()["task_id"]
        task_queue.update_status(id2, "passed", score=8.0, feedback="ok")

        r = client.get("/queue/list")
        assert r.status_code == 200
        body = r.json()
        ids = [t["task_id"] for t in body["tasks"]]
        assert id1 in ids
        assert id2 in ids
        assert body["count"] >= 2

    def test_list_invalid_status_returns_422(self, tmp_db):
        r = client.get("/queue/list?status=unknown")
        assert r.status_code == 422

    def test_list_response_has_expected_fields(self, tmp_db):
        """每筆任務要有精簡欄位（task_id/source/status/attempt_count/last_score/cost_usd/created_at）。"""
        client.post("/queue/push", json={"source": "B", "spec": _valid_spec()})
        r = client.get("/queue/list?status=pending")
        assert r.status_code == 200
        task = r.json()["tasks"][0]
        for field in ("task_id", "source", "status", "attempt_count", "last_score", "cost_usd", "created_at"):
            assert field in task, f"field '{field}' missing from list response"
        assert task["source"] == "B"


class TestQueueGetTask:
    """驗收點 5：GET /queue/task/{id} 找不到 → 404。"""

    def test_get_nonexistent_task_returns_404(self, tmp_db):
        r = client.get("/queue/task/does-not-exist-uuid")
        assert r.status_code == 404

    def test_get_existing_task_returns_detail(self, tmp_db):
        task_id = client.post("/queue/push", json={"spec": _valid_spec("detail test")}).json()["task_id"]
        r = client.get(f"/queue/task/{task_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["task_id"] == task_id
        assert body["status"] == "pending"
        assert "spec_json" in body  # 完整詳情，含 spec_json


class TestQueueSpentToday:
    """驗收點 6：spent_today_usd 正確反映 ledger。"""

    def test_spent_today_zero_when_no_ledger(self, tmp_db):
        r = client.get("/queue/status")
        assert r.status_code == 200
        assert r.json()["spent_today_usd"] == 0.0

    def test_spent_today_reflects_ledger_insert(self, tmp_db):
        """直接往 cost_ledger 寫入後，/queue/status 的 spent_today_usd 要更新。"""
        from orchestrator import task_queue

        task_id = client.post("/queue/push", json={"spec": _valid_spec()}).json()["task_id"]
        task_queue.ledger_insert(task_id, round_n=1, cost_usd=1.23)
        task_queue.ledger_insert(task_id, round_n=2, cost_usd=0.77)

        r = client.get("/queue/status")
        assert r.status_code == 200
        spent = r.json()["spent_today_usd"]
        assert abs(spent - 2.00) < 1e-9

    def test_cost_known_false_not_counted(self, tmp_db):
        """cost_known=False 的記錄（subprocess）不計入 SUM。"""
        from orchestrator import task_queue

        task_id = client.post("/queue/push", json={"spec": _valid_spec()}).json()["task_id"]
        task_queue.ledger_insert(task_id, round_n=1, cost_usd=0.0,
                                 cost_known=False, reason="subprocess_unknown")

        r = client.get("/queue/status")
        assert r.json()["spent_today_usd"] == 0.0
