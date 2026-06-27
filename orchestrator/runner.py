"""AgentOS 心跳 Runner — 外層任務執行迴圈

職責：
  1. 從 task_queue 取任務（FIFO）
  2. 呼叫 maker 執行，拿回 MakeResult（含 usage）
  3. 呼叫 run_verification 做單次驗收
  4. 依三停規則決定任務出口
  5. 累計全局成本，達上限停止心跳

三停規則（評估順序：撞線 → 達標 → 煞車）：
  ① 撞線停（dead）：score == 0.0（環境錯）→ 任務標 dead，絕不回收
  ② 達標停（passed）：score >= PASS_SCORE → 任務標 passed
  ③ 煞車停（escalated）：
       - 達到 max_rounds 上限
       - 連兩輪進步 < NO_PROGRESS_GAP
       - 同任務 attempt_count >= MAX_ATTEMPTS（防 Ralph Wiggum 假完成）
       - 全局成本 >= GLOBAL_BUDGET_USD（心跳停止前先把當前任務標 escalated）

成本守門：
  - runner 只累加，不計算單價（單價邏輯在 MakeResult.from_usage）
  - cost_known=False 的任務（subprocess executor）：
    不計入全局油表，但仍寫 cost_ledger（cost_usd=0.0, reason='subprocess_unknown'）
  - 全局油表持久化：cost_ledger 表（task_queue.db）
    · run_loop 啟動時呼叫 ledger_spent_today() 重建 spent_usd
    · run_one 每輪 make 完成後呼叫 ledger_insert() 寫流水
    · 時區 localtime（台灣午夜歸零），跨日自動清零
    · 重啟後 run_loop 從 DB 重建今日已花費，油表不歸零

審計：
  - 每個 round 的 make + verify 結果寫入 decision_log
  - 任務最終出口（pass/escalate/dead）也寫審計

設計原則：
  - runner 不自己計算單價，只累加 MakeResult.cost_usd
  - runner 不直接呼叫 litellm、不讀 settings
  - 三停計數（rounds / no_progress / attempt_count）完全在本層持有
  - run_verification() 維持單次呼叫，不改其介面
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Callable, Iterator

sys.path.insert(0, str(Path(__file__).parent.parent))

from contracts.task_spec import TaskSpec
from orchestrator import decision_log, task_queue
from orchestrator.loop import run_verification
from orchestrator.maker import MakeResult, make
from orchestrator.task_queue import ledger_insert, ledger_spent_today, ledger_update_task_cost
from orchestrator.metrics import record_eval
from orchestrator.auto_consolidate import auto_consolidate
from orchestrator import reflect

logger = logging.getLogger(__name__)

# ── 三停常數（可被呼叫方覆蓋） ────────────────────────────────────────────

PASS_SCORE: float = 7.0          # 達標閾值
MAX_ROUNDS: int = 5              # 煞車：最大輪次
NO_PROGRESS_GAP: float = 0.5    # 煞車：連兩輪進步不足此值視為停滯
MAX_ATTEMPTS: int = 2            # 煞車：同任務最多嘗試次數（防重複撿到假完成任務）
GLOBAL_BUDGET_USD: float = 5.00  # 撞線：全局油表上限


# ── 單任務執行 ───────────────────────────────────────────────────────────────

def run_one(
    task: dict[str, Any],
    *,
    spent_usd: float = 0.0,
    global_budget_usd: float = GLOBAL_BUDGET_USD,
    max_rounds: int = MAX_ROUNDS,
    pass_score: float = PASS_SCORE,
    no_progress_gap: float = NO_PROGRESS_GAP,
    max_attempts: int = MAX_ATTEMPTS,
    on_token: Callable[[str], None] | None = None,
) -> tuple[str, float]:
    """執行單一任務，回傳 (final_status, accumulated_cost_usd)。

    Parameters
    ----------
    task          : task_queue.next_pending() 回傳的 dict
    spent_usd     : 呼叫前已花費的全局成本（由 run_loop 傳入）
    global_budget_usd : 全局油表上限
    其餘參數      : 三停常數覆蓋（便於測試）
    on_token      : 串流 token 回調（可選）

    Returns
    -------
    (final_status, total_spent_usd_after_this_task)
      final_status ∈ {"passed", "escalated", "dead"}
    """
    task_id = task["task_id"]
    attempt_count = task["attempt_count"]  # 取出時已 +1
    spec = TaskSpec.model_validate_json(task["spec_json"])
    effective_max_rounds = min(max_rounds, spec.max_rounds)

    # ── 煞車：attempt_count 超限 ─────────────────────────────────────────────
    if attempt_count > max_attempts:
        logger.warning("[runner] task=%s escalated: attempt_count=%d > max_attempts=%d",
                       task_id, attempt_count, max_attempts)
        task_queue.update_status(
            task_id, "escalated",
            feedback=f"attempt_count {attempt_count} exceeded max_attempts {max_attempts}",
            notes={"reason": "max_attempts", "attempt_count": attempt_count},
        )
        _audit(task_id, "escalated", reason="max_attempts",
               attempt_count=attempt_count)
        return "escalated", spent_usd

    # ── Repair tasks (inspector source="A"): edit repo source, not code blobs ──
    # The generic make→verify path below grades self-contained blobs; a repo test
    # failure needs the real repair engine (reads + writes repo files, re-runs the
    # actual test). Delegate and return a queue-compatible (status, cost).
    fingerprint = (spec.io_example or {}).get("input", "")
    if spec.why.startswith("修復失敗測試") and "::" in fingerprint:
        return _run_repair_task(task_id, fingerprint, spent_usd,
                                global_budget_usd, effective_max_rounds)

    prev_score: float | None = None
    prev_prev_score: float | None = None
    local_cost: float = 0.0  # 本任務本次 attempt 累計成本

    for round_n in range(1, effective_max_rounds + 1):

        # ── 全局油表：每輪開始前先查 ─────────────────────────────────────────
        if spent_usd + local_cost >= global_budget_usd:
            logger.warning("[runner] task=%s escalated: global budget exhausted "
                           "(spent=%.4f, budget=%.2f)",
                           task_id, spent_usd + local_cost, global_budget_usd)
            task_queue.update_status(
                task_id, "escalated",
                score=prev_score,
                feedback="global budget exhausted",
                notes={"reason": "global_budget", "spent_usd": spent_usd + local_cost},
            )
            _audit(task_id, "escalated", reason="global_budget",
                   round_n=round_n, spent_usd=spent_usd + local_cost)
            ledger_update_task_cost(task_id, local_cost)
            return "escalated", spent_usd + local_cost

        # ── Make ──────────────────────────────────────────────────────────────
        logger.info("[runner] task=%s round=%d/%d making…", task_id, round_n, effective_max_rounds)
        try:
            make_result: MakeResult = make(spec, on_token=on_token)
        except Exception as exc:
            logger.error("[runner] task=%s round=%d make failed: %s", task_id, round_n, exc)
            task_queue.update_status(
                task_id, "escalated",
                score=0.0,
                feedback=f"make() raised: {exc}",
                notes={"reason": "make_exception", "error": str(exc)},
            )
            _audit(task_id, "escalated", reason="make_exception",
                   round_n=round_n, error=str(exc))
            ledger_update_task_cost(task_id, local_cost)
            return "escalated", spent_usd + local_cost

        # ── 成本累加 + 持久化到 cost_ledger ──────────────────────────────────
        # cost_known=True  → 計入 local_cost（影響油表）+ INSERT ledger
        # cost_known=False → 不計 local_cost，但 INSERT ledger（cost_usd=0, 審計用）
        if make_result.cost_known:
            local_cost += make_result.cost_usd
            ledger_insert(task_id, round_n, make_result.cost_usd,
                          cost_known=True, reason="litellm")
        else:
            logger.debug("[runner] task=%s round=%d cost_known=False (subprocess), "
                         "not counted toward budget", task_id, round_n)
            ledger_insert(task_id, round_n, 0.0,
                          cost_known=False, reason="subprocess_unknown")
        _audit_make(task_id, round_n, make_result)

        # ── Verify ───────────────────────────────────────────────────────────
        verdict = run_verification(spec, make_result.output,
                                   prev_score=prev_score,
                                   max_rounds=effective_max_rounds)
        score: float = verdict["score"]
        feedback: str = verdict["feedback"]
        v_status: str = verdict["status"]  # "pass" | "retry" | "escalate"

        # ── Record eval + consolidate ─────────────────────────────────────────
        try:
            record_eval(spec.why[:50], verdict.get("source", "unknown"), score, verdict.get("passed", False))
        except Exception:
            pass  # best-effort
        try:
            auto_consolidate(spec, verdict)
        except Exception:
            pass  # best-effort

        logger.info("[runner] task=%s round=%d score=%.1f status=%s",
                    task_id, round_n, score, v_status)
        _audit_verify(task_id, round_n, verdict)

        # ── 三停：撞線停（score==0.0 環境錯）→ dead ───────────────────────
        if score == 0.0:
            logger.warning("[runner] task=%s dead: score==0.0 at round=%d", task_id, round_n)
            task_queue.update_status(
                task_id, "dead",
                score=0.0,
                feedback=feedback,
                notes={"reason": "env_error", "round_n": round_n},
            )
            _audit(task_id, "dead", reason="env_error", round_n=round_n)
            ledger_update_task_cost(task_id, local_cost)
            return "dead", spent_usd + local_cost

        # ── 三停：達標停（score >= pass_score）→ passed ─────────────────────
        if score >= pass_score:
            logger.info("[runner] task=%s passed: score=%.1f at round=%d", task_id, round_n, score)
            task_queue.update_status(
                task_id, "passed",
                score=score,
                feedback=feedback,
                notes={"reason": "passed", "round_n": round_n},
            )
            _audit(task_id, "passed", reason="passed", round_n=round_n, score=score)
            # ── 反思：檢查是否需要調整系統閾值 ──────────────────────────────────────
            try:
                if reflect.should_propose():
                    proposal = reflect.build_proposal()
                    if proposal.reflections:
                        logger.info("[runner] reflect proposal: %s (%d reflections)",
                                    proposal.title, len(proposal.reflections))
            except Exception:
                pass
            ledger_update_task_cost(task_id, local_cost)
            return "passed", spent_usd + local_cost

        # ── 三停：煞車停：連兩輪停滯 ────────────────────────────────────────
        if prev_score is not None and prev_prev_score is not None:
            gap_this = score - prev_score
            gap_last = prev_score - prev_prev_score
            if gap_this < no_progress_gap and gap_last < no_progress_gap:
                logger.warning("[runner] task=%s escalated: no_progress "
                               "(scores: %.1f→%.1f→%.1f, gap<%.1f)",
                               task_id, prev_prev_score, prev_score, score, no_progress_gap)
                task_queue.update_status(
                    task_id, "escalated",
                    score=score,
                    feedback=feedback,
                    notes={"reason": "no_progress", "scores": [prev_prev_score, prev_score, score]},
                )
                _audit(task_id, "escalated", reason="no_progress",
                       round_n=round_n, score=score)
                ledger_update_task_cost(task_id, local_cost)
                return "escalated", spent_usd + local_cost

        prev_prev_score = prev_score
        prev_score = score

    # ── 三停：煞車停：max_rounds 耗盡 ────────────────────────────────────────
    logger.warning("[runner] task=%s escalated: max_rounds=%d exhausted", task_id, effective_max_rounds)
    task_queue.update_status(
        task_id, "escalated",
        score=prev_score,
        feedback=f"max_rounds {effective_max_rounds} exhausted without passing",
        notes={"reason": "max_rounds", "last_score": prev_score},
    )
    _audit(task_id, "escalated", reason="max_rounds",
           round_n=effective_max_rounds, score=prev_score)
    ledger_update_task_cost(task_id, local_cost)
    return "escalated", spent_usd + local_cost


def _run_repair_task(
    task_id: str,
    fingerprint: str,
    spent_usd: float,
    global_budget_usd: float,
    max_rounds: int,
) -> tuple[str, float]:
    """Delegate a repair task to orchestrator.repair (edits repo source, verifies
    with the REAL repo pytest). Maps the RepairResult onto the queue state machine."""
    if spent_usd >= global_budget_usd:
        task_queue.update_status(task_id, "escalated", feedback="global budget exhausted",
                                 notes={"reason": "global_budget", "spent_usd": spent_usd})
        _audit(task_id, "escalated", reason="global_budget", spent_usd=spent_usd)
        return "escalated", spent_usd

    from orchestrator import repair
    from orchestrator.maker import _load_settings
    repo_root = Path(__file__).parent.parent
    model = _load_settings().get("maker_model", "")
    try:
        res = repair.repair_task(fingerprint, model=model, repo_root=repo_root, max_rounds=max_rounds)
    except Exception as exc:
        logger.error("[runner] task=%s repair raised: %s", task_id, exc)
        task_queue.update_status(task_id, "escalated", score=0.0,
                                 feedback=f"repair raised: {exc}",
                                 notes={"reason": "repair_exception", "error": str(exc)})
        _audit(task_id, "escalated", reason="repair_exception", error=str(exc))
        return "escalated", spent_usd

    if res.cost_usd > 0:
        ledger_insert(task_id, res.rounds, res.cost_usd, cost_known=True, reason="repair")
        ledger_update_task_cost(task_id, res.cost_usd)

    if res.status == "passed":
        task_queue.update_status(task_id, "passed", score=10.0, feedback=res.feedback,
                                 notes={"reason": "repaired", "target": res.target, "rounds": res.rounds})
        _audit(task_id, "passed", reason="repaired", target=res.target, rounds=res.rounds)
    else:
        task_queue.update_status(task_id, "escalated", score=2.0, feedback=res.feedback,
                                 notes={"reason": "repair_failed", "rounds": res.rounds})
        _audit(task_id, "escalated", reason="repair_failed", rounds=res.rounds)
    logger.info("[runner] task=%s repair %s (target=%s rounds=%d cost=$%.5f)",
                task_id, res.status, res.target, res.rounds, res.cost_usd)
    return res.status, spent_usd + res.cost_usd


# ── 批次 Runner ──────────────────────────────────────────────────────────────

def run_loop(
    *,
    global_budget_usd: float = GLOBAL_BUDGET_USD,
    max_rounds: int = MAX_ROUNDS,
    pass_score: float = PASS_SCORE,
    no_progress_gap: float = NO_PROGRESS_GAP,
    max_attempts: int = MAX_ATTEMPTS,
    on_token: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """消耗佇列中所有 pending 任務，直到佇列空或全局預算耗盡。

    不含 sleep / cron / 自動醒來邏輯（那是 Trigger 層的責任）。
    手動呼叫一次 = 跑完當前佇列的一輪。

    Returns
    -------
    {
      "processed": int,         # 本次處理任務數
      "passed": int,
      "escalated": int,
      "dead": int,
      "spent_usd": float,       # 本次 run_loop 累計成本
      "budget_exhausted": bool,
    }
    """
    # 重建今日已花費（持久化油表，心跳重啟後不歸零）
    spent_usd: float = ledger_spent_today()
    if spent_usd > 0:
        logger.info("[runner] run_loop: restored spent_usd=%.4f from cost_ledger", spent_usd)
    stats: dict[str, int] = {"processed": 0, "passed": 0, "escalated": 0, "dead": 0}
    budget_exhausted = False

    while True:
        # 全局預算先查（進入下一個任務前）
        if spent_usd >= global_budget_usd:
            logger.warning("[runner] run_loop stopped: global budget exhausted (%.4f >= %.2f)",
                           spent_usd, global_budget_usd)
            budget_exhausted = True
            break

        # /goal 條件檢查：已完成目標則提早停止
        from orchestrator.state import goal_reached  # noqa: late import
        if goal_reached(stats):
            logger.info("[runner] run_loop stopped: /goal condition met")
            break

        task = task_queue.next_pending()
        if task is None:
            logger.info("[runner] run_loop: queue empty, stopping")
            break

        final_status, spent_usd = run_one(
            task,
            spent_usd=spent_usd,
            global_budget_usd=global_budget_usd,
            max_rounds=max_rounds,
            pass_score=pass_score,
            no_progress_gap=no_progress_gap,
            max_attempts=max_attempts,
            on_token=on_token,
        )
        stats["processed"] += 1
        stats[final_status] = stats.get(final_status, 0) + 1

    return {
        **stats,
        "spent_usd": spent_usd,
        "budget_exhausted": budget_exhausted,
    }


# ── 審計工具（私有） ──────────────────────────────────────────────────────────

def _audit(task_id: str, status: str, *, reason: str, **kwargs: Any) -> None:
    """寫入任務出口的審計記錄（失敗不阻塞主流程）。"""
    try:
        decision_log.record_request_trace(
            request_id=task_id,
            session_id=task_id,
            entrypoint="runner",
            raw_task=task_id,
            latest_status=status,
            notes={"reason": reason, **kwargs},
        )
    except Exception as exc:
        logger.debug("[runner] audit write failed (non-critical): %s", exc)


def _ensure_request_trace(task_id: str) -> None:
    """確保 request_trace 記錄存在（外鍵前置條件）。冪等，重複呼叫安全。"""
    try:
        decision_log.record_request_trace(
            request_id=task_id,
            session_id=task_id,
            entrypoint="runner",
            raw_task=task_id,
            latest_status="running",
        )
    except Exception:
        pass


def _audit_make(task_id: str, round_n: int, result: MakeResult) -> None:
    """寫入 make 結果的審計記錄。"""
    try:
        _ensure_request_trace(task_id)
        details: dict[str, Any] = {
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "cost_usd": result.cost_usd,
            "cost_known": result.cost_known,
        }
        decision_log.record_execution_route(
            request_id=task_id,
            session_id=task_id,
            round_n=round_n,
            decision="make",
            decision_source="runner",
            pre_policy_model=None,
            pre_policy_skills=None,
            pre_policy_tools=None,
            final_model="runner_make",
            final_skills=None,
            final_tools=None,
            policy_applied=False,
            policy_changed=False,
            requires_human_confirm=False,
            violations=None,
            details=details,
        )
    except Exception as exc:
        logger.debug("[runner] audit_make write failed (non-critical): %s", exc)


def _audit_verify(task_id: str, round_n: int, verdict: dict[str, Any]) -> None:
    """寫入 verify 結果的審計記錄。"""
    try:
        _ensure_request_trace(task_id)
        decision_log.record_execution_route(
            request_id=task_id,
            session_id=task_id,
            round_n=round_n,
            decision=f"verify_{verdict.get('status', 'unknown')}",
            decision_source="runner",
            pre_policy_model=None,
            pre_policy_skills=None,
            pre_policy_tools=None,
            final_model=verdict.get("source", ""),
            final_skills=None,
            final_tools=None,
            policy_applied=False,
            policy_changed=False,
            requires_human_confirm=False,
            violations=verdict.get("violations") or [],
            details={
                "score": verdict.get("score"),
                "feedback": verdict.get("feedback", "")[:500],
                "passed": verdict.get("passed"),
            },
        )
    except Exception as exc:
        logger.debug("[runner] audit_verify write failed (non-critical): %s", exc)
