"""
測試 orchestrator/runner.py

覆蓋項目（六分支 + 成本驗算 + cost_known=False 審計 + 油表持久化）：
  1. 達標停（passed）：score >= PASS_SCORE → status='passed'
  2. 煞車停：max_rounds 耗盡 → status='escalated'
  3. 煞車停：連兩輪無進步（no_progress）→ status='escalated'
  4. 煞車停：attempt_count 超限（max_attempts）→ status='escalated'
  5. 撞線停：score==0.0 環境錯（env_error）→ status='dead'
  6. 撞線停：全局預算超限（global_budget）→ status='escalated' + budget_exhausted=True
  7. 成本計算驗算：給定 token 數，斷言 cost_usd 正確
  8. cost_known=False：不計入全局油表，但有寫審計（decision_log 記錄）
  9. run_loop：跑完整個佇列，回傳正確統計
 10. 油表持久化：寫入 cost_ledger → 模擬重啟 → ledger_spent_today() 正確重建
 11. 跨日歸零：昨天的記錄不計入今日 SUM

所有測試用 mock maker（回傳可控的 score 序列 + usage），不真打 LLM。
"""
import os
import pytest
from unittest.mock import MagicMock, patch, call

from contracts.task_spec import TaskSpec
from orchestrator.maker import MakeResult, PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_spec(why: str = "test task") -> TaskSpec:
    return TaskSpec(
        why=why,
        io_example={"expected_output": "ok"},
        taste=[],
        boundaries=[],
        stop_on_metric="correctness",
        max_rounds=5,
    )


def _make_result(score: float, cost_known: bool = True,
                 prompt_tokens: int = 1000,
                 completion_tokens: int = 500) -> MakeResult:
    """建立可控的 MakeResult（mock maker 回傳值）。"""
    if cost_known:
        return MakeResult.from_usage("output", prompt_tokens, completion_tokens)
    else:
        return MakeResult.from_subprocess("output")


def _verdict(score: float) -> dict:
    """建立 run_verification 的模擬回傳值。"""
    if score >= 7.0:
        status = "pass"
        passed = True
    elif score == 0.0:
        status = "escalate"
        passed = False
    else:
        status = "retry"
        passed = False
    return {
        "status": status,
        "score": score,
        "feedback": f"score={score}",
        "passed": passed,
        "source": "pytest",
        "violations": [],
    }


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """每個測試一個獨立的臨時 SQLite DB（queue + decision_log）。"""
    db_queue = tmp_path / "queue.db"
    db_decision = tmp_path / "decisions.db"
    monkeypatch.setenv("AGENTOS_TASK_QUEUE_DB_PATH", str(db_queue))
    monkeypatch.setenv("AGENTOS_DECISIONS_DB_PATH", str(db_decision))
    from orchestrator import task_queue
    from orchestrator import decision_log
    task_queue._SCHEMA_ENSURED_FOR_PATH = ""
    decision_log._SCHEMA_ENSURED_FOR_PATH = ""
    task_queue.ensure_schema()
    decision_log.ensure_schema()
    yield tmp_path


def _push_task(spec: TaskSpec | None = None) -> dict:
    """放任務入佇列並立刻取出（status=running），回傳 task dict。"""
    from orchestrator import task_queue
    if spec is None:
        spec = _make_spec()
    task_id = task_queue.push(spec)
    task = task_queue.next_pending()
    assert task is not None and task["task_id"] == task_id
    return task


# ── 成本計算驗算 ──────────────────────────────────────────────────────────────

class TestMakeResultCost:
    def test_cost_calculation_v4_flash_price(self):
        """明確案例：100k input + 50k output，斷言 cost_usd 精確。"""
        prompt_tokens = 100_000
        completion_tokens = 50_000
        expected_cost = (
            prompt_tokens / 1_000_000 * PRICE_INPUT_PER_M
            + completion_tokens / 1_000_000 * PRICE_OUTPUT_PER_M
        )
        result = MakeResult.from_usage("out", prompt_tokens, completion_tokens)
        assert result.cost_usd == pytest.approx(expected_cost, rel=1e-6)
        assert result.cost_known is True

    def test_cost_v4_flash_exact_numbers(self):
        """100k input=$0.009, 50k output=$0.009, total=$0.018"""
        result = MakeResult.from_usage("out", 100_000, 50_000)
        # 0.09 * 0.1 + 0.18 * 0.05 = 0.009 + 0.009 = 0.018
        assert result.cost_usd == pytest.approx(0.018, abs=1e-9)

    def test_subprocess_cost_known_false(self):
        result = MakeResult.from_subprocess("out")
        assert result.cost_known is False
        assert result.cost_usd == 0.0
        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0

    def test_zero_tokens_zero_cost(self):
        result = MakeResult.from_usage("out", 0, 0)
        assert result.cost_usd == pytest.approx(0.0)


# ── 六分支三停測試 ────────────────────────────────────────────────────────────

class TestRunOneBranches:
    """用 mock maker + mock run_verification 驗證 runner 的三停六分支。"""

    def test_branch_1_passed_on_high_score(self, tmp_db):
        """分支①：score >= PASS_SCORE → passed。"""
        from orchestrator import runner
        task = _push_task()

        with patch("orchestrator.runner.make", return_value=_make_result(8.0)), \
             patch("orchestrator.runner.run_verification", return_value=_verdict(8.0)):
            status, cost = runner.run_one(task, pass_score=7.0, max_rounds=5)

        assert status == "passed"
        from orchestrator import task_queue
        assert task_queue.get_task(task["task_id"])["status"] == "passed"

    def test_branch_2_escalated_on_max_rounds(self, tmp_db):
        """分支②：max_rounds 耗盡，最終 score 未達標 → escalated。"""
        from orchestrator import runner
        task = _push_task()

        # 每輪都回傳 score=5.0（未達標），但有進步以免觸發 no_progress
        scores = [5.0, 5.5, 6.0]  # 3 輪就耗盡（max_rounds=3）
        verdicts = [_verdict(s) for s in scores]

        with patch("orchestrator.runner.make", return_value=_make_result(5.0)), \
             patch("orchestrator.runner.run_verification", side_effect=verdicts):
            status, cost = runner.run_one(task, pass_score=7.0, max_rounds=3)

        assert status == "escalated"
        from orchestrator import task_queue
        t = task_queue.get_task(task["task_id"])
        assert t["status"] == "escalated"
        assert t["notes"]["reason"] == "max_rounds"

    def test_branch_3_escalated_on_no_progress(self, tmp_db):
        """分支③：連兩輪進步 < NO_PROGRESS_GAP → escalated。"""
        from orchestrator import runner
        task = _push_task()

        # 輪次：3.0 → 3.1 → 3.15（兩次差距都 < 0.5）
        verdicts = [_verdict(3.0), _verdict(3.1), _verdict(3.15)]

        with patch("orchestrator.runner.make", return_value=_make_result(3.0)), \
             patch("orchestrator.runner.run_verification", side_effect=verdicts):
            status, cost = runner.run_one(task, pass_score=7.0, max_rounds=5,
                                          no_progress_gap=0.5)

        assert status == "escalated"
        from orchestrator import task_queue
        t = task_queue.get_task(task["task_id"])
        assert t["status"] == "escalated"
        assert t["notes"]["reason"] == "no_progress"

    def test_branch_4_escalated_on_max_attempts(self, tmp_db):
        """分支④：attempt_count > max_attempts → escalated（進場前即判斷）。"""
        from orchestrator import runner
        task = _push_task()
        # 手動將 attempt_count 設到超限
        task["attempt_count"] = 3  # max_attempts=2，3 > 2

        with patch("orchestrator.runner.make") as mock_make, \
             patch("orchestrator.runner.run_verification") as mock_verify:
            status, cost = runner.run_one(task, pass_score=7.0, max_attempts=2)

        assert status == "escalated"
        # make 和 verify 都不該被呼叫（進場前就判斷）
        mock_make.assert_not_called()
        mock_verify.assert_not_called()

        from orchestrator import task_queue
        t = task_queue.get_task(task["task_id"])
        assert t["status"] == "escalated"
        assert t["notes"]["reason"] == "max_attempts"

    def test_branch_5_dead_on_env_error(self, tmp_db):
        """分支⑤：score==0.0（環境錯）→ dead，且不被 next_pending 撿。"""
        from orchestrator import runner, task_queue

        # 放兩個任務（讓 dead 後能驗證後繼任務不受影響）
        spec = _make_spec("poison")
        task_id_poison = task_queue.push(spec)
        task_id_good = task_queue.push(_make_spec("good"))

        poison_task = task_queue.next_pending()
        assert poison_task["task_id"] == task_id_poison

        with patch("orchestrator.runner.make", return_value=_make_result(0.0)), \
             patch("orchestrator.runner.run_verification", return_value=_verdict(0.0)):
            status, cost = runner.run_one(poison_task, pass_score=7.0)

        assert status == "dead"
        assert task_queue.get_task(task_id_poison)["status"] == "dead"

        # dead 後 next_pending 應回傳 good task，不回收 poison
        next_task = task_queue.next_pending()
        assert next_task is not None
        assert next_task["task_id"] == task_id_good

    def test_branch_6_escalated_on_global_budget(self, tmp_db):
        """分支⑥：全局預算耗盡 → escalated（在第一輪 make 後判斷）。"""
        from orchestrator import runner
        task = _push_task()

        # cost_usd=3.0 的 make result；起始 spent_usd=4.0；3+4=7 > budget=5
        expensive_result = MakeResult(
            output="output", prompt_tokens=0, completion_tokens=0,
            cost_usd=3.0, cost_known=True,
        )

        with patch("orchestrator.runner.make", return_value=expensive_result), \
             patch("orchestrator.runner.run_verification", return_value=_verdict(5.0)):
            status, cost = runner.run_one(
                task,
                spent_usd=4.0,    # 進場前已花 $4
                global_budget_usd=5.0,  # 上限 $5
                pass_score=7.0,
                max_rounds=5,
            )

        # make 後 local_cost=3.0，4.0+3.0=7.0 >= 5.0，下一輪應 escalate
        # 注意：預算檢查在「每輪開始」——第一輪是在 make 後、第二輪開始前觸發
        assert status == "escalated"
        from orchestrator import task_queue
        t = task_queue.get_task(task["task_id"])
        assert t["status"] == "escalated"
        assert t["notes"]["reason"] == "global_budget"


# ── cost_known=False 不計入油表 ───────────────────────────────────────────────

class TestCostKnownFalse:
    def test_subprocess_cost_not_counted_toward_budget(self, tmp_db):
        """cost_known=False 的任務不計入全局油表，但任務本身正常完成。"""
        from orchestrator import runner
        task = _push_task()

        # subprocess make：cost_known=False，cost_usd=0 不應累入 spent
        subprocess_result = MakeResult.from_subprocess("good output")

        with patch("orchestrator.runner.make", return_value=subprocess_result), \
             patch("orchestrator.runner.run_verification", return_value=_verdict(8.0)):
            status, cost_after = runner.run_one(
                task,
                spent_usd=4.9,          # 幾乎要超限
                global_budget_usd=5.0,
                pass_score=7.0,
            )

        assert status == "passed"
        # cost_known=False：local_cost 沒有累加，spent_usd 維持進場前的值
        assert cost_after == pytest.approx(4.9)

    def test_subprocess_cost_writes_audit_cost_known_false(self, tmp_db):
        """cost_known=False 的任務有寫審計（decision_log）記錄 cost_known=False。"""
        import sqlite3
        from orchestrator import runner, decision_log

        task = _push_task()
        subprocess_result = MakeResult.from_subprocess("output")

        with patch("orchestrator.runner.make", return_value=subprocess_result), \
             patch("orchestrator.runner.run_verification", return_value=_verdict(8.0)):
            runner.run_one(task, pass_score=7.0)

        # 驗證 decision_log 中有記錄 cost_known=False
        decision_log.ensure_schema()
        db_path = decision_log.get_db_path()
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT details_json FROM routing_events WHERE request_id=? AND decision='make'",
            (task["task_id"],)
        ).fetchall()
        conn.close()

        assert len(rows) >= 1
        import json
        details = json.loads(rows[0][0])
        assert details["cost_known"] is False


# ── run_loop 批次測試 ─────────────────────────────────────────────────────────

class TestRunLoop:
    def test_run_loop_processes_all_pending(self, tmp_db):
        """run_loop 消耗佇列中所有 pending 任務。"""
        from orchestrator import runner, task_queue

        for i in range(3):
            task_queue.push(_make_spec(f"task {i}"))

        with patch("orchestrator.runner.make", return_value=_make_result(8.0)), \
             patch("orchestrator.runner.run_verification", return_value=_verdict(8.0)):
            result = runner.run_loop(pass_score=7.0, max_rounds=3)

        assert result["processed"] == 3
        assert result["passed"] == 3
        assert result["escalated"] == 0
        assert result["dead"] == 0
        assert task_queue.queue_depth("pending") == 0

    def test_run_loop_stops_on_budget_exhausted(self, tmp_db):
        """全局預算在 run_loop 層觸發停止心跳。"""
        from orchestrator import runner, task_queue

        for i in range(5):
            task_queue.push(_make_spec(f"task {i}"))

        # 每個任務花 $2，budget=$5 → 第三個任務開始前就停
        expensive = MakeResult(output="out", prompt_tokens=0, completion_tokens=0,
                               cost_usd=2.0, cost_known=True)

        with patch("orchestrator.runner.make", return_value=expensive), \
             patch("orchestrator.runner.run_verification", return_value=_verdict(8.0)):
            result = runner.run_loop(global_budget_usd=5.0, pass_score=7.0)

        assert result["budget_exhausted"] is True
        # 花了 2+2=4，第三個開始前 spent=4 < 5，執行第三個後 spent=6 >= 5
        # 但注意 run_loop 的預算檢查在「取下一個任務前」
        # 所以：task1(2$)=pass, task2(2$)=pass → spent=4 < 5 → task3 開始
        # task3 make 後 local_cost=2，下輪開始前 4+2=6 >= 5 → escalate
        # 再取 task4：spent=6 >= 5 → 立即停止
        assert result["processed"] >= 2
        assert result["budget_exhausted"] is True

    def test_run_loop_empty_queue(self, tmp_db):
        """佇列空時 run_loop 立即回傳，processed=0。"""
        from orchestrator import runner
        result = runner.run_loop()
        assert result["processed"] == 0
        assert result["budget_exhausted"] is False
        assert result["spent_usd"] == pytest.approx(0.0)

    def test_run_loop_mixed_outcomes(self, tmp_db):
        """run_loop 統計：passed + escalated + dead 各一。"""
        from orchestrator import runner, task_queue

        task_queue.push(_make_spec("pass task"))
        task_queue.push(_make_spec("dead task"))
        task_queue.push(_make_spec("max_rounds task"))

        # 依序回傳 verdict
        verdicts = [
            _verdict(8.0),   # pass task → passed
            _verdict(0.0),   # dead task → dead
            # max_rounds task：3 輪都未達標，max_rounds=3
            _verdict(5.0), _verdict(5.5), _verdict(6.0),
        ]

        with patch("orchestrator.runner.make", return_value=_make_result(5.0)), \
             patch("orchestrator.runner.run_verification", side_effect=verdicts):
            result = runner.run_loop(pass_score=7.0, max_rounds=3)

        assert result["processed"] == 3
        assert result["passed"] == 1
        assert result["dead"] == 1
        assert result["escalated"] == 1


# ── 整合：佇列 + runner 狀態機一致性 ─────────────────────────────────────────

class TestRunnerQueueIntegration:
    def test_passed_task_not_retriable(self, tmp_db):
        """passed 任務不再出現在 next_pending。"""
        from orchestrator import runner, task_queue

        task_queue.push(_make_spec())
        task = task_queue.next_pending()

        with patch("orchestrator.runner.make", return_value=_make_result(9.0)), \
             patch("orchestrator.runner.run_verification", return_value=_verdict(9.0)):
            runner.run_one(task, pass_score=7.0)

        assert task_queue.next_pending() is None

    def test_escalated_task_appears_in_triage(self, tmp_db):
        """escalated 任務出現在 list_triage。"""
        from orchestrator import runner, task_queue

        task_queue.push(_make_spec("needs triage"))
        task = task_queue.next_pending()

        verdicts = [_verdict(3.0), _verdict(3.1), _verdict(3.15)]
        with patch("orchestrator.runner.make", return_value=_make_result(3.0)), \
             patch("orchestrator.runner.run_verification", side_effect=verdicts):
            runner.run_one(task, pass_score=7.0, max_rounds=5, no_progress_gap=0.5)

        triage = task_queue.list_triage("escalated")
        assert any(t["task_id"] == task["task_id"] for t in triage)


# ── 油表持久化驗收（補洞的兩條） ─────────────────────────────────────────────

class TestLedgerPersistence:
    def test_spent_today_rebuilt_after_restart(self, tmp_db):
        """持久化驗收：寫 cost_ledger → 模擬重啟 → ledger_spent_today() 正確重建。

        這條測試正是「洞補上了」的證明：
        第一次 run_loop 跑完後 cost_ledger 有記錄；
        「重啟」後（新的 run_loop 呼叫，spent_usd 從 0 開始計算記憶體值）
        但從 DB 重建後能看到上一次的花費。
        """
        from orchestrator import task_queue

        # 直接呼叫 ledger_insert 模擬第一次 run_loop 已花費 $3.00
        task_queue.ledger_insert("task-aaa", 1, 2.0, cost_known=True, reason="litellm")
        task_queue.ledger_insert("task-aaa", 2, 1.0, cost_known=True, reason="litellm")

        # 模擬重啟：呼叫 ledger_spent_today()（就是 run_loop 啟動時的動作）
        spent = task_queue.ledger_spent_today()

        assert spent == pytest.approx(3.0, abs=1e-9), \
            f"重啟後應從 DB 重建 $3.00，但得到 {spent}"

    def test_spent_today_excludes_cost_known_false(self, tmp_db):
        """cost_known=False（subprocess）的記錄 cost_usd=0.0，不影響 SUM。"""
        from orchestrator import task_queue

        task_queue.ledger_insert("task-bbb", 1, 1.5, cost_known=True, reason="litellm")
        task_queue.ledger_insert("task-bbb", 2, 0.0, cost_known=False,
                                 reason="subprocess_unknown")

        spent = task_queue.ledger_spent_today()
        assert spent == pytest.approx(1.5, abs=1e-9)


class TestLedgerDateRollover:
    def test_yesterday_records_excluded_from_today_sum(self, tmp_db):
        """跨日歸零驗收：昨天的記錄不計入今日 SUM。

        直接用 SQL 插入一筆 local_date='yesterday' 的假記錄，
        再插一筆今天的，斷言 ledger_spent_today() 只算今天那筆。
        """
        import sqlite3
        from orchestrator import task_queue

        task_queue.ensure_schema()
        db_path = task_queue._db_path()
        now_iso = task_queue._now_iso()

        # 繞過 ledger_insert 直接寫昨天的記錄
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO cost_ledger
                  (task_id, round_n, cost_usd, cost_known, reason, local_date, created_at)
                VALUES ('yesterday-task', 1, 99.0, 1, 'litellm',
                        date('now','localtime','-1 day'), ?)
                """,
                (now_iso,),
            )

        # 今天再寫一筆 $2.00
        task_queue.ledger_insert("today-task", 1, 2.0, cost_known=True, reason="litellm")

        # 驗證：只算今天的 $2.00，昨天的 $99 不計入
        spent = task_queue.ledger_spent_today()
        assert spent == pytest.approx(2.0, abs=1e-9), \
            f"應只算今天 $2.00，但得到 {spent}（昨天的 $99 被誤計入）"

    def test_run_loop_restores_from_ledger_on_startup(self, tmp_db):
        """run_loop 啟動時從 ledger 重建 spent_usd，而非從 0 開始。

        場景：今天已花 $4.50（寫在 ledger），budget=$5.00。
        run_loop 啟動後應立即知道只剩 $0.50 額度，
        若佇列中有任務且每次 make 花 $1.00，第一個任務的第二輪應觸發全局預算停止。
        """
        from orchestrator import runner, task_queue

        # 預先寫入今日已花費 $4.50
        task_queue.ledger_insert("prev-task", 1, 4.50, cost_known=True, reason="litellm")

        # 佇列放一個任務
        task_queue.push(_make_spec("budget test"))

        # 每次 make 花 $1.00
        expensive = MakeResult(output="out", prompt_tokens=0, completion_tokens=0,
                               cost_usd=1.0, cost_known=True)

        with patch("orchestrator.runner.make", return_value=expensive), \
             patch("orchestrator.runner.run_verification", return_value=_verdict(5.0)):
            result = runner.run_loop(global_budget_usd=5.0, pass_score=7.0, max_rounds=3)

        # 啟動時 spent=4.50，第一輪 make 後 local_cost=1.0，4.50+1.0=5.50 >= 5.0
        # 第二輪開始前應觸發 global_budget → escalated，run_loop 停止
        assert result["budget_exhausted"] is True
        assert result["processed"] >= 1
