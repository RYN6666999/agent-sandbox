"""Session D Auto-Consolidate 測試。

verdict_to_experience 是純函式（pass/escalate/retry 三路）。
auto_consolidate 寫 gene 走真實 knowledge 層，沿用 test_knowledge.py 的
temp_knowledge_db pattern（tmp_path + AGENTOS_KNOWLEDGE_DB_PATH，gbrain disabled）。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from contracts.task_spec import TaskSpec
from orchestrator import auto_consolidate as ac
from orchestrator import knowledge


def _spec(why: str = "修好登入逾時的 off-by-one") -> TaskSpec:
    return TaskSpec(
        why=why,
        io_example={"input": why, "expected_output": ""},
        taste=[], boundaries=[], stop_on_metric="quality", max_rounds=5,
    )


@pytest.fixture()
def temp_knowledge_db(tmp_path, monkeypatch):
    db_path = tmp_path / "knowledge.db"
    monkeypatch.setenv("AGENTOS_KNOWLEDGE_DB_PATH", str(db_path))
    monkeypatch.setattr(
        knowledge, "_load_gbrain_config",
        lambda: {"url": "", "enabled": False, "token": ""},
    )
    assert knowledge.ensure_schema() is True
    yield db_path


# ── verdict_to_experience (pure) ───────────────────────────────────────────

def test_pass_maps_to_pattern_gene():
    exp = ac.verdict_to_experience(_spec(), {"status": "pass", "score": 10.0, "source": "pytest"})
    assert exp["type"] == "pattern"
    assert exp["domain"] == "workflow"
    assert exp["fix"] == ""
    assert exp["tags"] == ["pass", "pytest"]
    assert "通過驗收" in exp["what"]


def test_escalate_maps_to_bugfix_with_feedback_as_fix():
    verdict = {"status": "escalate", "score": 0.0, "source": "pytest", "feedback": "pytest timeout"}
    exp = ac.verdict_to_experience(_spec(), verdict)
    assert exp["type"] == "bug-fix"
    assert exp["fix"] == "pytest timeout"
    assert exp["tags"] == ["escalate", "pytest"]


def test_retry_is_skipped():
    assert ac.verdict_to_experience(_spec(), {"status": "retry", "score": 4.0}) is None


def test_missing_source_defaults_to_unknown():
    exp = ac.verdict_to_experience(_spec(), {"status": "pass", "score": 8.0})
    assert exp["tags"] == ["pass", "unknown"]


# ── auto_consolidate (writes brain) ────────────────────────────────────────

def test_auto_consolidate_writes_gene(temp_knowledge_db):
    genes = ac.auto_consolidate(_spec(), {"status": "pass", "score": 10.0, "source": "pytest"})
    assert len(genes) == 1
    assert genes[0]["key"].startswith("gene/workflow/")
    # round-trip: the gene is actually readable from the brain
    entry = knowledge.read_knowledge(genes[0]["key"])
    assert len(entry) >= 1


def test_auto_consolidate_skips_retry(temp_knowledge_db):
    assert ac.auto_consolidate(_spec(), {"status": "retry", "score": 3.0}) == []


def test_auto_consolidate_is_best_effort(monkeypatch):
    # consolidate blows up → auto_consolidate swallows and returns [], never raises.
    def boom(_experiences):
        raise RuntimeError("db exploded")
    monkeypatch.setattr(ac, "consolidate_experiences", boom)
    assert ac.auto_consolidate(_spec(), {"status": "pass", "score": 10.0, "source": "pytest"}) == []


# ── 合併偵測 ────────────────────────────────────────────────────────────────────

def test_consolidation_skips_similar(temp_knowledge_db):
    """寫入一個 gene 後，相似 verdict 應不產生新 entry。"""
    # 先寫一個 gene 進腦庫
    knowledge.write_knowledge(
        "gene/workflow/login-timeout",
        "任務通過驗收 (score 10.0, via pytest): 修好登入逾時的 off-by-one",
        metadata={"type": "pattern", "domain": "workflow"},
    )

    # 相似任務的 verdict → 應被偵測為重複
    spec = _spec("修好登入逾時的 off-by-one")
    verdict = {"status": "pass", "score": 10.0, "source": "pytest"}
    genes = ac.auto_consolidate(spec, verdict)
    assert genes == [], f"expected no new genes for similar content, got {genes}"


def test_prune_oldest(temp_knowledge_db, monkeypatch):
    """超過 max_entries 時應 prune 最舊條目。"""
    # Write enough entries to trigger prune
    for i in range(5):
        knowledge.write_knowledge(f"test/prune/{i}", f"entry {i}")

    # Set a very low max_entries to force pruning
    monkeypatch.setattr(ac, "PRUNE_MAX_ENTRIES", 3)

    # Verify there are 5 entries
    all_entries_before = knowledge.read_knowledge("test/prune/", limit=20)
    assert len(all_entries_before) == 5

    # Trigger auto_consolidate with a dummy pass (prune happens inside)
    ac.auto_consolidate(_spec("new unrelated task"),
                         {"status": "pass", "score": 10.0, "source": "pytest"})

    # At least some entries should have been removed
    all_entries_after = knowledge.read_knowledge("test/prune/", limit=20)
    assert len(all_entries_after) < 5, "prune should have removed oldest entries"


def test_failure_counter_increments(monkeypatch):
    """consolidate 失敗時，failure counter 應 +1。"""
    def boom(_experiences):
        raise RuntimeError("db exploded")
    monkeypatch.setattr(ac, "consolidate_experiences", boom)

    initial = ac.get_failure_count()
    ac.auto_consolidate(_spec("test"), {"status": "pass", "score": 10.0, "source": "pytest"})
    assert ac.get_failure_count() == initial + 1


def test_is_similar_match():
    """_is_similar 應能辨識相同任務描述。"""
    existing = {"content": "任務通過驗收 (score 10.0, via pytest): 修好登入逾時的 off-by-one"}
    new_exp = {"what": "任務通過驗收 (score 10.0, via pytest): 修好登入逾時的 off-by-one"}
    assert ac._is_similar(existing, new_exp) is True


def test_is_similar_no_match():
    """_is_similar 對不同任務應回傳 False。"""
    existing = {"content": "任務通過驗收 (score 10.0, via pytest): 修好登入逾時的 off-by-one"}
    new_exp = {"what": "任務通過驗收 (score 10.0, via pytest): 實作整數相加功能"}
    assert ac._is_similar(existing, new_exp) is False
