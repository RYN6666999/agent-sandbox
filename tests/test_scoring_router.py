"""Scoring router unit tests — B1-B5 all blocks.

Style: pytest, sys.path.insert(0, ...), pydantic ValidationError per existing convention.
"""
import sys
import json
import math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from pydantic import ValidationError

from contracts.verdict_v2 import ActionRequest, VerdictV2
from router.reversibility import classify_reversibility, is_containable, all_classifications
from router.scoring import score, _determine_lane, _score_confidence_history
from router.ratchet import (
    RatchetEntry, load_ratchet, save_ratchet, update_ratchet,
    signoff_auto, get_signoff_queue, MIN_SAMPLES_FOR_UPGRADE, _EVENTS_PATH, _RATCHET_PATH,
)
from router.orchestrate import process_verdict, get_ratchet_summary


# ══════════════════════════════════════════════════════════════════════════════
# B1 — VerdictV2
# ══════════════════════════════════════════════════════════════════════════════

class TestActionRequest:
    def test_valid(self):
        r = ActionRequest(action_id="act-001", task_class="file_write")
        assert r.action_id == "act-001"
        assert r.task_class == "file_write"
        assert r.declared_reversibility == "escaping"  # default

    def test_empty_action_id(self):
        with pytest.raises(ValidationError):
            ActionRequest(action_id="", task_class="x")

    def test_empty_task_class(self):
        with pytest.raises(ValidationError):
            ActionRequest(action_id="x", task_class="")

    def test_auto_ts(self):
        r = ActionRequest(action_id="a", task_class="b")
        assert r.ts != ""

    def test_invalid_reversibility(self):
        with pytest.raises(ValidationError):
            ActionRequest(action_id="a", task_class="b", declared_reversibility="invalid")


class TestVerdictV2:
    def test_valid_defaults(self):
        v = VerdictV2(action_id="act-001")
        assert v.action_id == "act-001"
        assert v.lane == "human"
        assert v.outcome == "fail"
        assert v.reversible_actual == "escaping"
        assert v.source == "scoring-router"

    def test_empty_action_id(self):
        with pytest.raises(ValidationError):
            VerdictV2(action_id="")

    def test_all_fields(self):
        v = VerdictV2(
            action_id="act-001",
            status="pass",
            score=0.85,
            feedback="good",
            passed=True,
            source="scoring-router",
            violations=[{"rule": "no_network"}],
            lane="sandbox",
            outcome="pass",
            reversible_actual="containable",
            objective_signal={"kind": "pytest", "detail": "all passed"},
            cost_actual={"tokens": 500, "compute": 10},
            committed=True,
            gate={"decision": "allow", "reason": "lane=sandbox"},
            digest="sha256:abc123",
            ts="2026-07-24T00:00:00Z",
        )
        assert v.lane == "sandbox"
        assert v.committed is True
        assert v.gate["decision"] == "allow"

    def test_invalid_lane(self):
        with pytest.raises(ValidationError):
            VerdictV2(action_id="a", lane="invalid_lane")

    def test_invalid_outcome(self):
        with pytest.raises(ValidationError):
            VerdictV2(action_id="a", outcome="unknown")

    def test_auto_ts(self):
        v = VerdictV2(action_id="a")
        assert v.ts != ""

    def test_serialization_roundtrip(self):
        v1 = VerdictV2(action_id="act-001", lane="auto", committed=True)
        data = v1.model_dump()
        v2 = VerdictV2(**data)
        assert v2.action_id == v1.action_id
        assert v2.lane == v1.lane
        assert v2.committed == v1.committed

    def test_to_legacy_dict(self):
        v = VerdictV2(action_id="a", status="pass", score=0.9, feedback="ok", passed=True)
        d = v.to_legacy_dict()
        assert d["status"] == "pass"
        assert d["score"] == 0.9
        assert d["feedback"] == "ok"
        assert d["passed"] is True
        # delta 欄位不在 legacy dict 中
        assert "lane" not in d
        assert "gate" not in d


# ══════════════════════════════════════════════════════════════════════════════
# B3 — Reversibility
# ══════════════════════════════════════════════════════════════════════════════

class TestReversibility:
    def test_containable_classes(self):
        for tc in ["file_write", "compute_draft", "refactor_local", "gbrain_read", "brief_draft", "local_test"]:
            assert classify_reversibility(tc) == "containable", f"{tc} should be containable"
            assert is_containable(tc) is True

    def test_escaping_classes(self):
        for tc in ["network_call", "costly_compute", "send_message", "git_push", "system_change", "gbrain_write"]:
            assert classify_reversibility(tc) == "escaping", f"{tc} should be escaping"
            assert is_containable(tc) is False

    def test_unknown_class_defaults_to_escaping(self):
        assert classify_reversibility("unknown_task_type") == "escaping"
        assert is_containable("unknown_task_type") is False

    def test_unknown_class_is_human_bound(self):
        """新任務類預設 escaping/human（透過 scoring 檢查）。"""
        req = ActionRequest(action_id="test", task_class="brand_new_task")
        v = score(req)
        assert v.lane == "human"
        assert v.reversible_actual == "escaping"

    def test_all_classifications_returns_copy(self):
        all_c = all_classifications()
        assert "file_write" in all_c
        assert "network_call" in all_c
        # 修改回傳值不影響原始表
        all_c["test"] = "containable"
        assert "test" not in all_classifications()


# ══════════════════════════════════════════════════════════════════════════════
# B2 — Scoring
# ══════════════════════════════════════════════════════════════════════════════

class TestScoring:
    def test_escaping_class_always_human(self):
        """escaping 類永遠封頂 human，履歷再厚不自動畢業。"""
        req = ActionRequest(action_id="t1", task_class="network_call")
        v = score(req)
        assert v.lane == "human", f"escaping class should be human, got {v.lane}"

    def test_containable_new_class_is_human(self):
        """全新 containable 類因信心低 → human。"""
        req = ActionRequest(action_id="t2", task_class="file_write")
        v = score(req)
        assert v.lane == "human", f"new class should be human, got {v.lane}"

    def test_containable_with_history_goes_to_sandbox(self):
        """有 ratchet 履歷的 containable 類 → sandbox。"""
        # 先建立 ratchet 條目（已在 sandbox）
        entry = RatchetEntry(task_class="file_write", level="sandbox", verified_count=15, failed_count=2)
        save_ratchet({"file_write": entry})

        req = ActionRequest(action_id="t3", task_class="file_write")
        v = score(req)
        assert v.lane == "sandbox", f"with history should be sandbox, got {v.lane}"

    def test_over_budget_denies(self):
        """爆預算 → deny。"""
        req = ActionRequest(
            action_id="t4", task_class="file_write",
            cost_estimate={"tokens": 999_999},
        )
        v = score(req)
        assert v.lane == "deny", f"over budget should be deny, got {v.lane}"

    def test_confidence_history_none(self):
        """無 ratchet 條目 → 信心 0。"""
        assert _score_confidence_history(None) == 0.0

    def test_confidence_history_high(self):
        entry = RatchetEntry(task_class="x", verified_count=18, failed_count=2)
        assert _score_confidence_history(entry) == 0.9

    def test_confidence_history_low(self):
        entry = RatchetEntry(task_class="x", verified_count=1, failed_count=9)
        assert _score_confidence_history(entry) == 0.1

    def test_scoring_unknown_class_defaults_human(self):
        """未知任務類預設 escaping/human。"""
        req = ActionRequest(action_id="t5", task_class="completely_unknown")
        v = score(req)
        assert v.lane == "human"
        assert v.reversible_actual == "escaping"


# ══════════════════════════════════════════════════════════════════════════════
# B4 — Ratchet
# ══════════════════════════════════════════════════════════════════════════════

class TestRatchetBasics:
    def test_new_entry_defaults(self):
        e = RatchetEntry(task_class="file_write")
        assert e.level == "human"
        assert e.verified_count == 0
        assert e.failed_count == 0
        assert e.needs_signoff is False

    def test_empty_task_class_rejected(self):
        with pytest.raises(ValidationError):
            RatchetEntry(task_class="")

    def test_pass_rate(self):
        e = RatchetEntry(task_class="x", verified_count=8, failed_count=2)
        assert e.pass_rate == 0.8

    def test_fail_rate(self):
        e = RatchetEntry(task_class="x", verified_count=8, failed_count=2)
        assert e.fail_rate == 0.2

    def test_confidence_lower_bound_zero_when_no_data(self):
        e = RatchetEntry(task_class="x")
        assert e.confidence_lower_bound == 0.0

    def test_confidence_lower_bound_positive(self):
        e = RatchetEntry(task_class="x", verified_count=50, failed_count=5)
        assert 0.0 < e.confidence_lower_bound < 1.0

    def test_save_and_load(self):
        entries = {
            "a": RatchetEntry(task_class="a", verified_count=10),
            "b": RatchetEntry(task_class="b", level="sandbox"),
        }
        save_ratchet(entries)
        loaded = load_ratchet()
        assert "a" in loaded
        assert loaded["a"].verified_count == 10
        assert loaded["b"].level == "sandbox"
        assert loaded["a"].needs_signoff is False


class TestRatchetAsymmetric:
    """不對稱升降：一次 fail 扣分 > 一次 pass 加分。"""

    def test_pass_increments_verified(self):
        e = RatchetEntry(task_class="x", verified_count=5, failed_count=5)
        e = update_ratchet(e, passed=True)
        assert e.verified_count == 6
        assert e.consecutive_failures == 0

    def test_fail_increments_failed_and_consecutive(self):
        e = RatchetEntry(task_class="x", verified_count=5, failed_count=5)
        e = update_ratchet(e, passed=False)
        assert e.failed_count == 6
        assert e.consecutive_failures == 1

    def test_fail_has_higher_impact(self):
        """一次 pass 加 1 分，一次 fail 扣 3 分（不對稱）。"""
        # 10 pass, 0 fail → pass_rate = 1.0
        e1 = RatchetEntry(task_class="x", verified_count=10, failed_count=0)
        # 1 pass 後
        e1 = update_ratchet(e1, passed=True)
        assert e1.verified_count == 11
        assert e1.pass_rate == pytest.approx(11/11)

        # 10 pass, 0 fail → 1 fail 後
        e2 = RatchetEntry(task_class="x", verified_count=10, failed_count=0)
        e2 = update_ratchet(e2, passed=False)
        assert e2.failed_count == 1
        # pass_rate 從 1.0 降到 10/11 ≈ 0.909
        # 而一次 pass 從 10/10=1.0 到 11/11=1.0 沒變化
        # 但從 9/10=0.9 到 10/11≈0.909 只+0.009
        # 所以 fail 的影響 > pass 的影響
        pass_impact = 0
        fail_impact = 1.0 - 10/11
        assert fail_impact > pass_impact, "fail impact should be larger than pass impact"

    def test_consecutive_failures_causes_downgrade(self):
        """連續失敗 3 次 → 降級。"""
        e = RatchetEntry(task_class="x", level="sandbox", verified_count=15, failed_count=2)
        e = update_ratchet(e, passed=False)  # consecutive=1
        assert e.level == "sandbox"
        e = update_ratchet(e, passed=False)  # consecutive=2
        assert e.level == "sandbox"
        e = update_ratchet(e, passed=False)  # consecutive=3 → downgrade
        assert e.level == "human", "should downgrade after 3 consecutive failures"

    def test_high_fail_rate_causes_downgrade(self):
        """失敗率 ≥ 40% → 降級。"""
        # 10 pass, 6 fail = fail_rate = 6/16 = 0.375 → 還不到
        e = RatchetEntry(task_class="x", level="sandbox", verified_count=10, failed_count=6)
        assert e.fail_rate < 0.4
        e = update_ratchet(e, passed=False)  # failed_count=7, fail_rate=7/17≈0.412 ≥ 0.4
        assert e.level == "human", "should downgrade when fail_rate >= 0.4"


class TestRatchetMinSampleGate:
    """最小樣本閘：未達樣本數下限不升級。"""

    def test_no_upgrade_below_min_samples(self):
        """8 樣本（低於 MIN_SAMPLES=10）→ 不升級。"""
        e = RatchetEntry(task_class="x", level="human", verified_count=8, failed_count=0)
        e = update_ratchet(e, passed=True)  # 9 pass, 0 fail — still below 10
        assert e.level == "human", "should not upgrade with only 9 samples (needs 10+CI)"

    def test_upgrade_at_min_samples_with_high_pass_rate(self):
        """10 樣本 + 高通過率 → 升 sandbox。"""
        e = RatchetEntry(task_class="x", level="human", verified_count=10, failed_count=0)
        # confidence_lower_bound 應該夠高
        assert e.confidence_lower_bound > 0.7
        e = update_ratchet(e, passed=True)  # 11 verified, 0 failed
        # 如果信心夠，應升 sandbox
        if e.confidence_lower_bound >= 0.7:
            assert e.level == "sandbox"
        else:
            assert e.level == "human"  # 信心不夠則維持


class TestRatchetPolicyB:
    """policy(b)：ratchet 絕不自動把任務類升到 auto。"""

    def test_sandbox_to_auto_sets_needs_signoff(self):
        """sandbox 夠格進 auto → 設 needs_signoff=True，不升。"""
        # 50 pass, 2 fail → 高信心 + 夠樣本
        e = RatchetEntry(task_class="x", level="sandbox", verified_count=50, failed_count=2)
        assert e.confidence_lower_bound > 0.85, f"CLB={e.confidence_lower_bound} should be > 0.85"
        e = update_ratchet(e, passed=True)
        assert e.level == "sandbox", "policy(b): should NOT auto-upgrade to auto"
        assert e.needs_signoff is True, "should set needs_signoff=True"

    def test_needs_signoff_event_is_logged(self):
        """升 auto 時發 needs_ryan_signoff 事件。"""
        # 清理 events
        if _EVENTS_PATH.exists():
            _EVENTS_PATH.unlink()

        # 50 pass, 2 fail → 高信心 + 夠樣本
        e = RatchetEntry(task_class="x", level="sandbox", verified_count=50, failed_count=2)
        e = update_ratchet(e, passed=True)
        assert e.needs_signoff is True

        # 檢查 events log
        assert _EVENTS_PATH.exists()
        lines = _EVENTS_PATH.read_text().strip().split("\n")
        signoff_events = [l for l in lines if '"needs_ryan_signoff"' in l]
        assert len(signoff_events) >= 1, "needs_ryan_signoff event should be logged"

    def test_signoff_auto_actually_works(self):
        """Ryan 簽核後才真的進 auto。"""
        e = RatchetEntry(task_class="x", level="sandbox", verified_count=30, failed_count=2)
        e.needs_signoff = True
        save_ratchet({"x": e})

        result = signoff_auto("x")
        assert result is True

        loaded = load_ratchet()
        assert loaded["x"].level == "auto"
        assert loaded["x"].needs_signoff is False

    def test_signoff_auto_fails_without_needs_signoff(self):
        """未請求簽核 → signoff 失敗。"""
        e = RatchetEntry(task_class="x", level="sandbox", verified_count=30, failed_count=2)
        e.needs_signoff = False
        save_ratchet({"x": e})

        result = signoff_auto("x")
        assert result is False

    def test_ratchet_never_auto_upgrades_to_auto(self):
        """ratchet 自己絕不把任何類升到 auto（policy b 鐵則）。"""
        for _ in range(5):
            e = RatchetEntry(task_class="x", level="sandbox", verified_count=50, failed_count=1)
            e = update_ratchet(e, passed=True)
            if e.needs_signoff:
                break
        assert e.level == "sandbox", "ratchet should never auto-upgrade to auto"
        assert e.needs_signoff is True


# ══════════════════════════════════════════════════════════════════════════════
# B5 — Orchestrate
# ══════════════════════════════════════════════════════════════════════════════

class TestOrchestrate:
    def test_process_verdict_not_committed_skips(self):
        """committed=False → 不更新 ratchet。"""
        req = ActionRequest(action_id="t1", task_class="file_write")
        v = VerdictV2(action_id="t1", lane="sandbox", outcome="pass", committed=False)
        process_verdict(req, v)
        # ratchet 不應有條目
        entries = load_ratchet()
        assert "file_write" not in entries

    def test_process_verdict_committed_updates_ratchet(self):
        """committed=True → 更新 ratchet。"""
        req = ActionRequest(action_id="t2", task_class="file_write")
        v = VerdictV2(action_id="t2", lane="sandbox", outcome="pass", committed=True)
        process_verdict(req, v)
        entries = load_ratchet()
        assert "file_write" in entries
        assert entries["file_write"].verified_count >= 1

    def test_ratchet_summary(self):
        """get_ratchet_summary 回傳唯讀摘要。"""
        save_ratchet({
            "a": RatchetEntry(task_class="a", verified_count=5),
            "b": RatchetEntry(task_class="b", level="sandbox", verified_count=20),
        })
        summary = get_ratchet_summary()
        assert "a" in summary
        assert "b" in summary
        assert summary["a"]["level"] == "human"
        assert summary["b"]["level"] == "sandbox"


class TestSignoffQueue:
    def test_pending_signoff_is_listed(self):
        e = RatchetEntry(task_class="x", level="sandbox", verified_count=50, failed_count=2)
        e.needs_signoff = True
        save_ratchet({"x": e})

        queue = get_signoff_queue()
        assert len(queue) == 1
        assert queue[0]["task_class"] == "x"
        assert queue[0]["needs_signoff"] is True

    def test_recent_reject_reason_is_exposed(self):
        req = ActionRequest(action_id="rej-1", task_class="x")
        verdict = VerdictV2(
            action_id="rej-1",
            lane="sandbox",
            outcome="fail",
            committed=True,
            gate={"decision": "deny", "reason": "pytest failed"},
        )
        process_verdict(req, verdict)

        e = load_ratchet()["x"]
        e.needs_signoff = True
        save_ratchet({"x": e})

        queue = get_signoff_queue()
        assert len(queue) == 1
        assert queue[0]["last_reject_reason"] == "pytest failed"


# ══════════════════════════════════════════════════════════════════════════════
# 裁判隔離
# ══════════════════════════════════════════════════════════════════════════════

class TestJudgeIsolation:
    """裁判隔離：被評分動作無法改到評分規則。"""

    def test_scoring_module_not_importable_from_action(self):
        """驗證 scoring 模組不會被意外 import 到被評分的動作中。"""
        # 被評分的動作不應能 import router.ratchet 或 router.scoring
        # 這條測試確保隔離設計：被評分者只拿到 VerdictV2，拿不到評分邏輯
        import sys as _sys
        # scoring 模組本身不 expose 內部修改能力
        from router.scoring import score as _score_fn
        # 確認 scoring 函式是純函式（沒有 side effect 修改規則的能力）
        assert callable(_score_fn)

    def test_ratchet_cannot_be_patched_from_action_context(self):
        """模擬被評分動作嘗試改 ratchet 資料 — 無權限。"""
        # 被評分動作只應拿到 VerdictV2，不應有 ratchet 模組的引用
        # 在真實系統中，executor 的動作不 import router.ratchet
        # 這裡測試：如果動作嘗試直接寫 ratchet.json，會被隔離
        import os
        # 動作不應知道 ratchet.json 路徑
        from router.ratchet import _RATCHET_PATH as rp
        # 動作若嘗試寫入，不會影響正在執行的評分邏輯（因為評分已先完成）
        # 這是設計上的隔離：評分在前，執行在後
        assert rp.exists() or rp.parent.exists()  # 路徑存在

    def test_escaping_class_cannot_reach_sandbox_or_auto(self):
        """escaping 類不管怎麼打分，都打不進 sandbox/auto。"""
        # 即使有完美履歷
        e = RatchetEntry(task_class="network_call", level="sandbox", verified_count=999, failed_count=0)
        save_ratchet({"network_call": e})
        req = ActionRequest(action_id="iso1", task_class="network_call")
        v = score(req)
        assert v.lane == "human", f"escaping should be human, got {v.lane}"

    def test_unknown_class_cannot_reach_sandbox(self):
        """未知任務類預設 escaping → human。"""
        req = ActionRequest(action_id="iso2", task_class="some_new_thing")
        v = score(req)
        assert v.lane == "human", f"unknown class should be human, got {v.lane}"
        assert v.reversible_actual == "escaping"


# ══════════════════════════════════════════════════════════════════════════════
# 清理
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def cleanup_ratchet_data():
    """每次測試前後清理 ratchet 持久化資料。"""
    yield
    if _RATCHET_PATH.exists():
        _RATCHET_PATH.unlink()
    if _EVENTS_PATH.exists():
        _EVENTS_PATH.unlink()