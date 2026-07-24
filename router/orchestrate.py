"""串接 — 路由器讀 Verdict → 更新 ratchet 履歷。

全在本 repo 內，不跨 neuralis。
"""
from contracts.verdict_v2 import ActionRequest, VerdictV2
from router.ratchet import load_ratchet, save_ratchet, update_ratchet, _append_event


def process_verdict(request: ActionRequest, verdict: VerdictV2) -> None:
    """收到 Verdict v2 後：
    1. 如果 verdict.committed == True → 更新 ratchet（成功/失敗）
    2. 檢查是否有任務類需要發 signoff 事件
    3. 寫審計 digest
    """
    if not verdict.committed:
        return  # 沙箱撤回，不更新 ratchet

    entries = load_ratchet()
    entry = entries.get(request.task_class)

    if entry is None:
        # 全新任務類 → 建立初始條目
        from router.ratchet import RatchetEntry
        entry = RatchetEntry(task_class=request.task_class)

    # 更新 ratchet
    passed = verdict.outcome == "pass"
    entry = update_ratchet(entry, passed)
    entries[request.task_class] = entry
    save_ratchet(entries)

    # 寫審計 digest
    gate = verdict.gate if isinstance(verdict.gate, dict) else {}
    _append_event(
        entry,
        "verdict_processed",
        f"action_id={request.action_id} outcome={verdict.outcome} digest={verdict.digest}",
        metadata={
            "action_id": request.action_id,
            "outcome": verdict.outcome,
            "lane": verdict.lane,
            "gate_decision": gate.get("decision", ""),
            "gate_reason": gate.get("reason", ""),
            "digest": verdict.digest,
            "committed": verdict.committed,
        },
    )


def get_ratchet_summary() -> dict:
    """回傳所有任務類的 ratchet 狀態摘要（唯讀）。"""
    entries = load_ratchet()
    return {
        tc: {
            "level": e.level,
            "verified_count": e.verified_count,
            "failed_count": e.failed_count,
            "pass_rate": round(e.pass_rate, 3),
            "needs_signoff": e.needs_signoff,
        }
        for tc, e in sorted(entries.items())
    }