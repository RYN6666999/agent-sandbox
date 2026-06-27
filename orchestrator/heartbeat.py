"""AgentOS Trigger — 心跳排程器

職責：定期喚醒 inspector + runner，構成自修復迴圈的最後一棒。
它是「最笨的東西」：一個計時器，不含任何業務邏輯。

核心設計：
  run_once()   — 執行一拍：預檢油表 → 巡檢 → 跑任務 → 記 log
  run_forever() — daemon：while True: run_once(); sleep(interval)

油表協調（Ryan 裁決，2026-06-22）：
  - heartbeat 預檢 = 「門口保全」：budget 已耗盡時跳過 inspector（省 120s）
  - run_loop 內部 = 「逐任務 ATM」：取出每個 task 前再守一次
  - 兩者互補，不衝突：同一個 ledger_spent_today() 冪等唯讀，讀幾次都安全
  - 邊界情況：預檢通過但 120s 後沒錢了 → run_loop 自己 break，heartbeat 不管

預算常數：
  GLOBAL_BUDGET_USD 唯一定義在 runner.py（62 行），這裡 import 而非重複定義。
  heartbeat 把同一個值傳進 run_loop，閾值全程只有一個來源。

停止語意（Ryan 裁決，2026-06-22）：
  預算耗盡時繼續 sleep（不 sys.exit），等 localtime 跨日 cost_ledger 自動歸零。
  log 需清楚寫「budget exhausted, sleeping until rollover」，避免看 log 以為卡死。
"""
from __future__ import annotations

import logging
import signal
import sys
import random as _random
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.runner import GLOBAL_BUDGET_USD, run_loop
from orchestrator import inspector as _inspector
from orchestrator import task_queue
from orchestrator.state import load_state, update_from_beat

# ── 常數 ─────────────────────────────────────────────────────────────────────

DEFAULT_INTERVAL_SECONDS: int = 300   # 每拍間隔：5 分鐘

# ── 可變頻率 ─────────────────────────────────────────────────────────────────
DEFAULT_MIN_INTERVAL: int = 60     # 佇列忙碌時最短間隔（秒）
DEFAULT_MAX_INTERVAL: int = 600    # 佇列空閒時最長間隔（秒）
INTERVAL_QUEUE_THRESHOLD: int = 3  # 超過此深度視為忙碌

BEAT_LOG_PREFIX: str = "[heartbeat]"

logger = logging.getLogger(__name__)


def _calculate_interval(
    queue_depth: int,
    min_interval: int = DEFAULT_MIN_INTERVAL,
    max_interval: int = DEFAULT_MAX_INTERVAL,
    queue_threshold: int = INTERVAL_QUEUE_THRESHOLD,
) -> int:
    """根據佇列深度計算下次心跳間隔。

    queue_depth >= threshold -> min_interval（最快）
    queue_depth == 0         -> max_interval（最慢）
    中間值線性插值。
    """
    if queue_depth >= queue_threshold:
        return min_interval
    if queue_depth <= 0:
        return max_interval
    ratio = queue_depth / queue_threshold
    return max_interval - int((max_interval - min_interval) * ratio)


def _get_queue_depth() -> int:
    """Read current queue depth safely. Returns 0 on error."""
    try:
        from orchestrator import task_queue as _tq
        return _tq.queue_depth("pending")
    except Exception:
        return 0


# ── 單拍邏輯 ─────────────────────────────────────────────────────────────────

def run_once(
    *,
    global_budget_usd: float = GLOBAL_BUDGET_USD,
    beat_n: int = 0,
) -> dict[str, Any]:
    """執行一拍心跳。

    流程：
      0. 讀 state.json（agent forgets, file remembers）
      1. 讀油表（ledger_spent_today）：預算耗盡 → log + return early
      2. 執行 inspector.run_inspection()（最多 PYTEST_TIMEOUT=120s）
      3. 執行 runner.run_loop()（傳入同一個 global_budget_usd）
      4. log 本拍摘要
      5. 更新 state.json
      6. 回傳本拍結果 dict

    回傳格式：
    {
        "beat_n": int,
        "budget_exhausted_pre": bool,   # 預檢即發現耗盡
        "spent_before": float,          # 預檢時的已花費
        "inspection": dict | None,      # inspector 結果（若 budget 耗盡則 None）
        "loop": dict | None,            # run_loop 結果（若 budget 耗盡 / inspector 出錯則 None）
        "budget_exhausted_post": bool,  # run_loop 回報的 budget_exhausted
    }
    """
    logger.info("%s beat #%d started (budget=%.2f)", BEAT_LOG_PREFIX, beat_n, global_budget_usd)

    # ── Step 0：讀狀態檔案 — agent 會忘記，但檔案記得 ──────────────────────────
    _state = load_state()
    logger.info(
        "%s prior state — beat=%d last_run=%s status=%s queue=%d",
        BEAT_LOG_PREFIX,
        _state.get("last_beat_n", 0),
        _state.get("last_run", "never"),
        _state.get("last_beat_status", "unknown"),
        _state.get("queue_depth", 0),
    )

    # ── Step 1：門口保全 — 油表預檢 ──────────────────────────────────────────
    spent_before = task_queue.ledger_spent_today()
    if spent_before >= global_budget_usd:
        logger.warning(
            "%s beat #%d — budget exhausted (%.4f >= %.2f), "
            "sleeping until rollover (localtime midnight)",
            BEAT_LOG_PREFIX, beat_n, spent_before, global_budget_usd,
        )
        result = {
            "beat_n": beat_n,
            "budget_exhausted_pre": True,
            "spent_before": spent_before,
            "inspection": None,
            "loop": None,
            "budget_exhausted_post": True,
            "queue_depth": 0,
            "next_interval": 0,  # outside caller decides
        }
        update_from_beat(result)
        return result

    logger.info(
        "%s beat #%d — oil gauge %.4f / %.2f, proceeding to inspection",
        BEAT_LOG_PREFIX, beat_n, spent_before, global_budget_usd,
    )

    # ── Step 2：巡檢 ─────────────────────────────────────────────────────────
    inspection = _inspector.run_inspection()
    logger.info(
        "%s beat #%d inspection done — exit_code=%s, failed=%d, pushed=%d, skipped=%d",
        BEAT_LOG_PREFIX, beat_n,
        inspection.get("exit_code"),
        inspection.get("total_failed", 0),
        inspection.get("pushed", 0),
        inspection.get("skipped_duplicate", 0),
    )

    # ── Step 3：跑任務 ────────────────────────────────────────────────────────
    # 把同一個 global_budget_usd 傳入 run_loop，閾值只有一個來源
    loop = run_loop(global_budget_usd=global_budget_usd)
    budget_exhausted_post = bool(loop.get("budget_exhausted", False))

    logger.info(
        "%s beat #%d run_loop done — processed=%d, passed=%d, escalated=%d, dead=%d, "
        "spent=%.4f, budget_exhausted=%s",
        BEAT_LOG_PREFIX, beat_n,
        loop.get("processed", 0),
        loop.get("passed", 0),
        loop.get("escalated", 0),
        loop.get("dead", 0),
        loop.get("spent_usd", 0.0),
        budget_exhausted_post,
    )

    if budget_exhausted_post:
        logger.warning(
            "%s beat #%d — budget exhausted after run_loop (%.4f >= %.2f), "
            "sleeping until rollover (localtime midnight)",
            BEAT_LOG_PREFIX, beat_n,
            task_queue.ledger_spent_today(),
            global_budget_usd,
        )

    # ── 定期 prune 腦庫（機率觸發，~每 50 拍約 ~4 小時一次） ───────────────────
    if _random.random() < 0.02:
        try:
            from orchestrator.auto_consolidate import prune_knowledge as _prune
            result_p = _prune()
            if result_p.get("removed", 0):
                logger.info("%s pruned %d stale brain entries", BEAT_LOG_PREFIX, result_p["removed"])
        except Exception:
            pass

    # ── 定期執行 eval scenarios（機率觸發，~每 50 拍一次，不花 LLM 預算） ───
    if _random.random() < 0.02:
        try:
            from scripts.run_eval import run_all as _run_eval
            eval_result = _run_eval()
            logger.info("%s eval: %d/%d passed (%d/%d free via safety+clarify)",
                        BEAT_LOG_PREFIX, eval_result["passed"], eval_result["total"],
                        eval_result["by_category"].get("sensitive", {}).get("passed", 0)
                        + eval_result["by_category"].get("danger", {}).get("passed", 0),
                        eval_result["total"])
        except Exception:
            pass

    # ── 更新 state.json ───────────────────────────────────────────────────────
    result = {
        "beat_n": beat_n,
        "budget_exhausted_pre": False,
        "spent_before": spent_before,
        "inspection": inspection,
        "loop": loop,
        "budget_exhausted_post": budget_exhausted_post,
        "queue_depth": _get_queue_depth(),
    }
    update_from_beat(result)
    return result


# ── daemon ────────────────────────────────────────────────────────────────────

def run_forever(
    *,
    interval: int = DEFAULT_INTERVAL_SECONDS,
    global_budget_usd: float = GLOBAL_BUDGET_USD,
    min_interval: int = DEFAULT_MIN_INTERVAL,
    max_interval: int = DEFAULT_MAX_INTERVAL,
) -> None:
    """無限心跳 daemon。

    每拍：run_once() → sleep(interval)。
    預算耗盡時繼續睡（不 exit），等 localtime 跨日 cost_ledger 歸零後自然復活。
    KeyboardInterrupt / SIGTERM 正常結束。
    """
    current_interval = interval
    logger.info(
        "%s daemon started (initial_interval=%ds, min=%ds, max=%ds, budget=%.2f)",
        BEAT_LOG_PREFIX, current_interval, min_interval, max_interval, global_budget_usd,
    )
    beat_n = 0

    # ── SIGTERM handler ─────────────────────────────────────────────────────────
    def _handle_sigterm(signum, frame):
        logger.warning("%s received SIGTERM, shutting down gracefully after %d beats",
                       BEAT_LOG_PREFIX, beat_n)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    try:
        while True:
            try:
                result = run_once(global_budget_usd=global_budget_usd, beat_n=beat_n)
                # 根據佇列深度調整下次間隔
                queue_depth = _get_queue_depth()
                new_interval = _calculate_interval(
                    queue_depth, min_interval=min_interval, max_interval=max_interval,
                )
                if new_interval != current_interval:
                    logger.info(
                        "%s beat #%d — interval adjusted: %ds -> %ds (queue_depth=%d)",
                        BEAT_LOG_PREFIX, beat_n, current_interval, new_interval, queue_depth,
                    )
                    current_interval = new_interval
            except Exception:
                # 單拍異常不能讓 daemon 掛掉：記錯誤繼續 sleep
                logger.exception("%s beat #%d raised unexpected exception", BEAT_LOG_PREFIX, beat_n)
            beat_n += 1
            logger.info(
                "%s sleeping %ds until next beat #%d", BEAT_LOG_PREFIX, current_interval, beat_n,
            )
            time.sleep(current_interval)
    except KeyboardInterrupt:
        logger.info("%s daemon stopped by KeyboardInterrupt after %d beats", BEAT_LOG_PREFIX, beat_n)
    except SystemExit:
        logger.info("%s daemon stopped by SystemExit after %d beats", BEAT_LOG_PREFIX, beat_n)


# ── CLI 入口 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="AgentOS heartbeat daemon — 定期喚醒 inspector + runner"
    )
    parser.add_argument(
        "--interval", type=int, default=DEFAULT_INTERVAL_SECONDS,
        help=f"每拍間隔秒數（預設 {DEFAULT_INTERVAL_SECONDS}）",
    )
    parser.add_argument(
        "--budget", type=float, default=GLOBAL_BUDGET_USD,
        help=f"全局油表上限 USD（預設 {GLOBAL_BUDGET_USD}）",
    )
    parser.add_argument(
        "--min-interval", type=int, default=DEFAULT_MIN_INTERVAL,
        help=f"最短心跳間隔秒數（預設 {DEFAULT_MIN_INTERVAL}）",
    )
    parser.add_argument(
        "--max-interval", type=int, default=DEFAULT_MAX_INTERVAL,
        help=f"最長心跳間隔秒數（預設 {DEFAULT_MAX_INTERVAL}）",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="只跑一拍就結束（除錯用）",
    )
    args = parser.parse_args()

    if args.once:
        result = run_once(global_budget_usd=args.budget, beat_n=0)
        import json as _json
        print(_json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0)
    else:
        run_forever(
            interval=args.interval, global_budget_usd=args.budget,
            min_interval=args.min_interval, max_interval=args.max_interval,
        )
