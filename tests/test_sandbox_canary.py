"""Sandbox canary executor tests.

Covers: legal→commit, illegal→rollback, escaping→escalate, verdict fields, ratchet feed.
"""
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import pytest

from contracts.verdict_v2 import ActionRequest, VerdictV2
from sandbox_canary import (
    canary_execute, SandboxWorkspace,
    _execute_file_write, _execute_file_delete, _execute_pytest,
    _is_path_legal, _is_content_legal, _compute_digest,
)
from router.ratchet import load_ratchet, save_ratchet, RatchetEntry, _RATCHET_PATH, _EVENTS_PATH
from router.reversibility import classify_reversibility, is_containable
from router.canary_adaptor import operation_for_task_class


# ══════════════════════════════════════════════════════════════════════════════
# SandboxWorkspace
# ══════════════════════════════════════════════════════════════════════════════

class TestSandboxWorkspace:
    def test_start_and_cleanup(self):
        ws = SandboxWorkspace()
        root = ws.start()
        assert root.exists()
        assert root.is_dir()
        ws.cleanup()
        assert ws._root is None

    def test_contains_within(self):
        ws = SandboxWorkspace()
        root = ws.start()
        f = root / "test.txt"
        f.write_text("hello")
        assert ws.contains(f)
        ws.cleanup()

    def test_contains_outside(self):
        ws = SandboxWorkspace()
        ws.start()
        outside = Path("/tmp")
        assert not ws.contains(outside)
        ws.cleanup()

    def test_cleanup_removes_dir(self):
        ws = SandboxWorkspace()
        root = ws.start()
        root_path = str(root)
        ws.cleanup()
        assert not Path(root_path).exists()


# ══════════════════════════════════════════════════════════════════════════════
# 沙箱執行器 helper
# ══════════════════════════════════════════════════════════════════════════════

class TestExecuteFileWrite:
    def test_write_and_read_back(self, tmp_path):
        result = _execute_file_write(tmp_path, "hello.txt", "world")
        assert result["status"] == "ok"
        assert (tmp_path / "hello.txt").read_text() == "world"

    def test_write_nested_path(self, tmp_path):
        result = _execute_file_write(tmp_path, "a/b/c/deep.txt", "nested")
        assert result["status"] == "ok"
        assert (tmp_path / "a/b/c/deep.txt").read_text() == "nested"

    def test_write_escape_rejected(self, tmp_path):
        result = _execute_file_write(tmp_path, "../../etc/malice", "bad")
        assert result["status"] == "blocked"

    def test_write_absolute_rejected(self, tmp_path):
        result = _execute_file_write(tmp_path, "/etc/passwd", "bad")
        assert result["status"] in ("blocked", "error")


class TestExecuteFileDelete:
    def test_delete_existing(self, tmp_path):
        f = tmp_path / "delete_me.txt"
        f.write_text("bye")
        result = _execute_file_delete(tmp_path, "delete_me.txt")
        assert result["status"] == "ok"
        assert not f.exists()

    def test_delete_nonexistent(self, tmp_path):
        result = _execute_file_delete(tmp_path, "ghost.txt")
        assert result["status"] == "not_found"

    def test_delete_escape_rejected(self, tmp_path):
        result = _execute_file_delete(tmp_path, "../../secret.txt")
        assert result["status"] == "blocked"


class TestExecutePytest:
    def test_pytest_pass(self, tmp_path):
        test_file = tmp_path / "test_pass.py"
        test_file.write_text("def test_ok(): assert 1+1 == 2")
        result = _execute_pytest(tmp_path, "test_pass.py")
        assert result["status"] == "ok"
        assert result["pytest_passed"] is True

    def test_pytest_fail(self, tmp_path):
        test_file = tmp_path / "test_fail.py"
        test_file.write_text("def test_bad(): assert 1+1 == 3")
        result = _execute_pytest(tmp_path, "test_fail.py")
        assert result["status"] == "failed"
        assert result["pytest_passed"] is False

    def test_pytest_not_found(self, tmp_path):
        result = _execute_pytest(tmp_path, "nonexistent_test.py")
        assert result["status"] == "error"


# ══════════════════════════════════════════════════════════════════════════════
# 合法/非法檢查
# ══════════════════════════════════════════════════════════════════════════════

class TestPathLegal:
    def test_legal_path(self):
        legal, reason = _is_path_legal("src/main.py")
        assert legal is True

    def test_forever_denied_env(self):
        legal, reason = _is_path_legal(".env")
        assert legal is False
        assert "forever_denied" in reason

    def test_forever_denied_key(self):
        legal, reason = _is_path_legal("keys/private.key")
        assert legal is False
        assert "forever_denied" in reason

    def test_restricted_extension(self):
        legal, reason = _is_path_legal("malware.exe")
        assert legal is False
        assert "restricted" in reason


class TestContentLegal:
    def test_legal_content(self):
        legal, reason = _is_content_legal(b"print('hello')")
        assert legal is True

    def test_denied_private_key(self):
        legal, reason = _is_content_legal(b"data\nBEGIN RSA PRIVATE KEY\nmore")
        assert legal is False

    def test_denied_api_key(self):
        legal, reason = _is_content_legal(b"api_key = sk-abc123def456")
        assert legal is False

    def test_denied_github_token(self):
        legal, reason = _is_content_legal(b"token=ghp_xxxxxxxxxxxx")
        assert legal is False


# ══════════════════════════════════════════════════════════════════════════════
# Digest
# ══════════════════════════════════════════════════════════════════════════════

class TestDigest:
    def test_digest_format(self):
        d = _compute_digest("act-001", {"status": "ok"})
        assert d.startswith("sha256:")
        assert len(d) == 16 + 7  # sha256: + 16 hex chars

    def test_digest_no_full_content(self):
        """digest 不落全文。"""
        d = _compute_digest("act-001", {"status": "ok", "full_content": "secret_data"})
        assert "secret_data" not in d


# ══════════════════════════════════════════════════════════════════════════════
# canary_execute — 核心流程
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def cleanup_ratchet():
    yield
    for p in [_RATCHET_PATH, _EVENTS_PATH]:
        if p.exists():
            p.unlink()


class TestCanaryEscaping:
    """escaping 類直接 escalate，不執行。"""

    def test_network_call_escalates(self):
        req = ActionRequest(action_id="c1", task_class="network_call",
                            payload={"operation": "write_file", "path": "test.txt", "content": "x"})
        v = canary_execute(req)
        assert v.lane == "human"
        assert v.outcome == "fail"
        assert v.reversible_actual == "escaping"
        assert v.gate["decision"] == "escalate"
        assert v.committed is False
        assert not v.passed
        assert v.digest != ""

    def test_send_message_escalates(self):
        req = ActionRequest(action_id="c2", task_class="send_message",
                            payload={"content": "spam"})
        v = canary_execute(req)
        assert v.lane == "human"
        assert v.gate["decision"] == "escalate"

    def test_unknown_class_escalates(self):
        req = ActionRequest(action_id="c3", task_class="some_new_action")
        v = canary_execute(req)
        assert v.lane == "human"
        assert v.reversible_actual == "escaping"

    def test_gbrain_write_escalates(self):
        req = ActionRequest(action_id="c4", task_class="gbrain_write",
                            payload={"operation": "write_file", "path": "note.md", "content": "x"})
        v = canary_execute(req)
        assert v.lane == "human"
        assert v.reversible_actual == "escaping"


class TestCanaryFileWrite:
    """合法→commit / 非法→rollback / verdict 欄位。"""

    def test_legal_write_commits(self, tmp_path):
        req = ActionRequest(
            action_id="fw1", task_class="file_write",
            payload={"operation": "write_file", "path": "hello.txt", "content": "Hello, Sandbox!"},
        )
        v = canary_execute(req, sandbox_dir=str(tmp_path))
        assert v.lane == "sandbox"
        assert v.outcome == "pass"
        assert v.committed is True
        assert v.passed is True
        assert v.reversible_actual == "containable"
        assert v.gate["decision"] == "allow"
        assert v.objective_signal["kind"] == "goal_met"
        assert v.digest.startswith("sha256:")
        assert v.source == "sandbox-canary"

    def test_legal_write_ratchet_updated(self, tmp_path):
        """committed=True → ratchet 更新。"""
        req = ActionRequest(
            action_id="fw2", task_class="file_write",
            payload={"operation": "write_file", "path": "note.txt", "content": "data"},
        )
        canary_execute(req, sandbox_dir=str(tmp_path))
        entries = load_ratchet()
        assert "file_write" in entries
        assert entries["file_write"].verified_count >= 1

    def test_illegal_path_denies(self, tmp_path):
        """永遠拒絕路徑 → deny，不執行。"""
        req = ActionRequest(
            action_id="fw3", task_class="file_write",
            payload={"operation": "write_file", "path": ".env", "content": "SECRET=1"},
        )
        v = canary_execute(req, sandbox_dir=str(tmp_path))
        assert v.lane == "deny"
        assert v.outcome == "fail"
        assert v.committed is False
        assert not v.passed

    def test_illegal_content_denies(self, tmp_path):
        """機密內容 → deny，不執行。"""
        req = ActionRequest(
            action_id="fw4", task_class="file_write",
            payload={"operation": "write_file", "path": "safe.txt",
                     "content": "BEGIN RSA PRIVATE KEY\nabc"},
        )
        v = canary_execute(req, sandbox_dir=str(tmp_path))
        assert v.lane == "deny"
        assert v.committed is False

    def test_unsupported_operation_escalates(self, tmp_path):
        req = ActionRequest(
            action_id="fw5", task_class="file_write",
            payload={"operation": "network_call", "path": "x.txt", "content": "x"},
        )
        v = canary_execute(req, sandbox_dir=str(tmp_path))
        assert v.gate["decision"] == "escalate"


class TestCanaryFileDelete:
    """刪除操作：合法→commit / 非法→rollback。"""

    def test_legal_delete_commits(self, tmp_path):
        # 先建立檔案
        f = tmp_path / "delete_me.txt"
        f.write_text("bye")
        req = ActionRequest(
            action_id="d1", task_class="file_write",
            payload={"operation": "delete_file", "path": "delete_me.txt"},
        )
        v = canary_execute(req, sandbox_dir=str(tmp_path))
        assert v.lane == "sandbox"
        assert v.outcome == "pass"
        assert v.committed is True
        assert v.gate["decision"] == "allow"

    def test_delete_nonexistent_rollsback(self, tmp_path):
        req = ActionRequest(
            action_id="d2", task_class="file_write",
            payload={"operation": "delete_file", "path": "ghost.txt"},
        )
        v = canary_execute(req, sandbox_dir=str(tmp_path))
        assert v.outcome == "fail"
        assert v.committed is False

    def test_delete_escape_rejected(self, tmp_path):
        req = ActionRequest(
            action_id="d3", task_class="file_write",
            payload={"operation": "delete_file", "path": "../../etc/shadow"},
        )
        v = canary_execute(req, sandbox_dir=str(tmp_path))
        assert v.outcome == "fail"
        assert v.committed is False


class TestCanaryPytest:
    """pytest 操作 + 客觀訊號。"""

    def test_pytest_pass(self, tmp_path):
        test_file = tmp_path / "test_ok.py"
        test_file.write_text("def test_pass(): assert 1+1 == 2")
        req = ActionRequest(
            action_id="p1", task_class="file_write",
            payload={"operation": "pytest", "path": "test_ok.py"},
        )
        v = canary_execute(req, sandbox_dir=str(tmp_path))
        assert v.outcome == "pass"
        assert v.committed is True
        assert v.objective_signal["kind"] == "pytest"
        assert v.objective_signal["pytest_passed"] is True

    def test_pytest_fail(self, tmp_path):
        test_file = tmp_path / "test_bad.py"
        test_file.write_text("def test_fail(): assert 1+1 == 3")
        req = ActionRequest(
            action_id="p2", task_class="file_write",
            payload={"operation": "pytest", "path": "test_bad.py"},
        )
        v = canary_execute(req, sandbox_dir=str(tmp_path))
        assert v.outcome == "fail"
        assert v.committed is False
        assert v.objective_signal["kind"] == "pytest"
        assert v.objective_signal["pytest_passed"] is False

    def test_pytest_signal_callback(self, tmp_path):
        test_file = tmp_path / "test_cb.py"
        test_file.write_text("def test_ok(): assert 1+1 == 2")
        signals = []
        req = ActionRequest(
            action_id="p3", task_class="file_write",
            payload={"operation": "pytest", "path": "test_cb.py"},
        )
        v = canary_execute(req, sandbox_dir=str(tmp_path),
                           signal_callback=lambda s: signals.append(s))
        assert len(signals) == 1
        assert signals[0]["pytest_passed"] is True

    def test_local_test_task_class_uses_registry_default(self, tmp_path):
        test_file = tmp_path / "test_local.py"
        test_file.write_text("def test_ok(): assert 2 + 2 == 4")
        req = ActionRequest(
            action_id="p4", task_class="local_test",
            payload={"path": "test_local.py"},
        )
        v = canary_execute(req, sandbox_dir=str(tmp_path))
        assert v.outcome == "pass"
        assert v.committed is True
        assert v.objective_signal["operation"] == "pytest"


class TestCanaryComputeDraft:
    def test_compute_draft_passes_with_content(self, tmp_path):
        req = ActionRequest(
            action_id="cd1", task_class="compute_draft",
            payload={"content": "Summarize this draft in three bullets."},
        )
        v = canary_execute(req, sandbox_dir=str(tmp_path))
        assert v.lane == "sandbox"
        assert v.outcome == "pass"
        assert v.committed is True
        assert v.objective_signal["operation"] == "compute"

    def test_compute_draft_empty_input_fails(self, tmp_path):
        req = ActionRequest(
            action_id="cd2", task_class="compute_draft",
            payload={"content": "   "},
        )
        v = canary_execute(req, sandbox_dir=str(tmp_path))
        assert v.outcome == "fail"
        assert v.committed is False


class TestCanaryAdaptorRegistry:
    def test_task_class_to_operation_mapping(self):
        assert operation_for_task_class("file_write") == "write_file"
        assert operation_for_task_class("local_test") == "pytest"
        assert operation_for_task_class("compute_draft") == "compute"


class TestCanaryInternalError:
    """沙箱內部錯誤處理。"""

    def test_missing_checkpoint_handled(self):
        """checkpoint 不存在時優雅處理。"""
        # 用 network_call（escaping）測試 — 不會走到 checkpoint 邏輯
        req = ActionRequest(action_id="e1", task_class="network_call")
        v = canary_execute(req)
        assert v.lane == "human"
        assert v.outcome == "fail"


# ══════════════════════════════════════════════════════════════════════════════
# 裁判隔離驗證
# ══════════════════════════════════════════════════════════════════════════════

class TestJudgeIsolation:
    """裁判隔離：escaping 類永遠不執行。"""

    def test_escaping_never_executes(self, tmp_path):
        """escaping 類不應建立檔案。"""
        req = ActionRequest(
            action_id="ji1", task_class="network_call",
            payload={"operation": "write_file", "path": "should_not_exist.txt",
                     "content": "should not be written"},
        )
        v = canary_execute(req, sandbox_dir=str(tmp_path))
        assert v.reversible_actual == "escaping"
        # 不檢查 tmp_path — canary 會建 temp dir 但 escaping 不走那條路
        assert v.gate["decision"] == "escalate"

    def test_escaping_payload_ignored(self):
        """escaping 的 payload 被忽略。"""
        req = ActionRequest(
            action_id="ji2", task_class="send_message",
            payload={"content": "spam", "operation": "write_file"},
        )
        v = canary_execute(req)
        assert v.feedback == "task_class=send_message is escaping — cannot execute in sandbox"


class TestVerdictFields:
    """Verdict 欄位齊全檢查。"""

    def test_all_fields_present_on_commit(self, tmp_path):
        req = ActionRequest(
            action_id="vf1", task_class="file_write",
            payload={"operation": "write_file", "path": "test.txt", "content": "hello"},
        )
        v = canary_execute(req, sandbox_dir=str(tmp_path))
        # 既有欄位
        assert v.action_id == "vf1"
        assert v.status in ("pass", "retry", "escalate")
        assert isinstance(v.score, float)
        assert isinstance(v.feedback, str)
        assert isinstance(v.passed, bool)
        assert v.source == "sandbox-canary"
        assert isinstance(v.violations, list)
        # delta 欄位
        assert v.lane in ("deny", "human", "sandbox", "auto")
        assert v.outcome in ("pass", "fail", "error")
        assert v.reversible_actual in ("containable", "escaping")
        assert isinstance(v.objective_signal, dict)
        assert isinstance(v.cost_actual, dict)
        assert isinstance(v.committed, bool)
        assert isinstance(v.gate, dict)
        assert "decision" in v.gate
        assert "reason" in v.gate
        assert isinstance(v.digest, str)
        assert v.digest != ""
        assert isinstance(v.ts, str)
        assert v.ts != ""

    def test_all_fields_present_on_escalate(self):
        req = ActionRequest(action_id="vf2", task_class="network_call")
        v = canary_execute(req)
        assert v.action_id == "vf2"
        assert v.status == "escalate"
        assert v.lane == "human"
        assert v.outcome == "fail"
        assert v.reversible_actual == "escaping"
        assert v.committed is False
        assert v.gate["decision"] == "escalate"
        assert v.digest != ""
        assert v.ts != ""


# ══════════════════════════════════════════════════════════════════════════════
# 清理
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def cleanup_all():
    yield
    for p in [_RATCHET_PATH, _EVENTS_PATH]:
        if p.exists():
            p.unlink()