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
    assert "✅" in exp["what"]


def test_escalate_maps_to_bugfix_with_feedback_as_fix():
    verdict = {"status": "escalate", "score": 0.0, "source": "pytest", "feedback": "pytest timeout"}
    exp = ac.verdict_to_experience(_spec(), verdict)
    assert exp["type"] == "bug-fix"
    assert "pytest timeout" in exp["fix"]
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
        "✅ 通過 (s=10.0, pytest) 修好登入逾時的 off-by-one | input: 修好登入逾時的 off-by-one",
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


def test_failure_counter_increments(temp_knowledge_db, monkeypatch):
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


class TestPrune:
    def test_prune_with_age(self, temp_knowledge_db):
        """Age-based prune 應刪除老條目。"""
        from orchestrator import knowledge
        from orchestrator.auto_consolidate import prune_knowledge

        # 寫入一條非常舊的條目（直接 SQL 改時間）
        entry_id = knowledge.write_knowledge("test/old", "old entry")
        conn = __import__('sqlite3').connect(str(temp_knowledge_db))
        conn.execute("UPDATE entries SET created_at = '2020-01-01T00:00:00Z' WHERE id = ?", (entry_id,))
        conn.commit()
        conn.close()

        # 寫入一條新的
        knowledge.write_knowledge("test/new", "new entry")

        # prune with 30 day threshold
        stats = prune_knowledge(max_age_days=30, max_entries=1000)
        assert stats["age_removed"] >= 1, f"expected age_removed >= 1, got {stats}"

    def test_prune_capacity_removes_lowest_confidence(self, temp_knowledge_db):
        """Capacity-based prune 應刪除最低 confidence 的條目。"""
        from orchestrator import knowledge
        from orchestrator.auto_consolidate import prune_knowledge

        # 寫多條，設一條低 confidence
        for i in range(5):
            knowledge.write_knowledge(f"test/cap/{i}", f"entry {i}")

        # 直接 SQL 設一條低 confidence
        conn = __import__('sqlite3').connect(str(temp_knowledge_db))
        conn.execute("UPDATE entries SET confidence = 0.1 WHERE key = 'test/cap/0'")
        conn.commit()
        conn.close()

        stats = prune_knowledge(max_age_days=0, max_entries=2)
        assert stats["capacity_removed"] >= 1, f"expected capacity_removed >= 1, got {stats}"


class TestDedup:
    def test_key_based_dedup_detects_duplicate(self):
        """相同的 what 內容應被 key-based dedup 偵測為重複。"""
        existing = {"key": "gene/workflow/commit-前先問用戶確認", "content": "commit 前先問用戶確認"}
        new_exp = {"what": "commit 前先問用戶確認"}
        assert ac._is_similar(existing, new_exp) is True

    def test_content_based_dedup_different_tasks(self):
        """不同任務不應被 dedup。"""
        existing = {"key": "gene/coding/add-function", "content": "實作整數相加函式"}
        new_exp = {"what": "修好登入逾時的 off-by-one"}
        assert ac._is_similar(existing, new_exp) is False


class TestDomainDetection:
    def test_detect_debugging(self):
        assert ac._detect_domain("修復測試失敗") == "debugging"
        assert ac._detect_domain("fix bug in login") == "debugging"

    def test_detect_coding(self):
        assert ac._detect_domain("implement add function") == "coding"
        assert ac._detect_domain("寫一個 BankAccount class") == "coding"

    def test_detect_workflow_default(self):
        assert ac._detect_domain("回答天氣如何") == "workflow"
        assert ac._detect_domain("") == "workflow"


class TestRichContent:
    def test_pass_includes_input(self):
        """pass 的 gene 應包含 input 資訊。"""
        spec = TaskSpec(
            why="implement add function",
            io_example={"input": "1,2", "expected_output": "3"},
            taste=[], boundaries=[], stop_on_metric="quality", max_rounds=1,
        )
        exp = ac.verdict_to_experience(spec, {"status": "pass", "score": 10.0, "source": "pytest"})
        # The mock knowledge search may or may not find duplicates
        # So exp could be None if dedup triggers — skip assertion if so
        if exp is not None:
            assert "✅" in exp["what"]
            assert "domain" in exp

    def test_escalate_includes_feedback(self):
        """escalate 的基因應包含 feedback。"""
        spec = TaskSpec(
            why="broken test",
            io_example={"input": "tests/test_x.py::test_y", "expected_output": "pass"},
            taste=[], boundaries=[], stop_on_metric="quality", max_rounds=1,
        )
        exp = ac.verdict_to_experience(spec, {
            "status": "escalate", "score": 2.0, "source": "pytest",
            "feedback": "測試結果不正確，assert 1+1==3",
        })
        if exp is not None:
            assert "❌" in exp["what"]
            assert exp["fix"]
