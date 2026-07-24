"""沙箱 canary 執行器 — 收 ActionRequest → checkpoint → 真跑 → 裁判 verdict。

生命週期：
  收 ActionRequest
  → escaping 類直接 gate=escalate 不執行
  → containable 類：checkpoint → 真跑 → 收集客觀訊號 → 合法 commit / 非法 rollback
  → 產 VerdictV2（reversible_actual 裁判覆核、committed、objective_signal、gate、digest）
  → 餵 router/orchestrate.py 更新 ratchet

與既有沙箱的關係：
  - 複用 mcp_server/sandbox/checkpoint.py 的 Checkpoint.create / restore
  - 內建精簡版 write_file/delete_file（避免直接依賴 mcp_server 的 Config/WorkspaceHandle）
  - digest 不落全文。裁判覆核 reversible_actual，不信自報。
"""
from __future__ import annotations
import hashlib
import os
import stat
import tempfile
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Callable

from contracts.verdict_v2 import ActionRequest, VerdictV2
from router.canary_adaptor import SUPPORTED_OPERATIONS, resolve_operation
from router.reversibility import classify_reversibility, is_containable
from router.orchestrate import process_verdict


# ── 沙箱 workspace 管理 ─────────────────────────────────────────────────────

class SandboxWorkspace:
    """沙箱臨時工作區。每次 canary 執行在獨立 temp dir。"""

    def __init__(self, base_dir: str | Path | None = None):
        self._tmpdir: tempfile.TemporaryDirectory | None = None
        self._root: Path | None = None
        self._base_dir = Path(base_dir) if base_dir else None

    @property
    def root(self) -> Path:
        if self._root is None:
            raise RuntimeError("workspace not started")
        return self._root

    def start(self) -> Path:
        """建立沙箱工作區。如果提供了 base_dir，直接以它為 workspace root。"""
        if self._base_dir:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            self._root = self._base_dir
        else:
            self._tmpdir = tempfile.TemporaryDirectory()
            self._root = Path(self._tmpdir.name)
        return self._root

    def cleanup(self) -> None:
        if self._tmpdir:
            try:
                self._tmpdir.cleanup()
            except OSError:
                pass
            self._tmpdir = None
            self._root = None

    def contains(self, path: Path) -> bool:
        """確認路徑在沙箱內。resolve 兩邊避免 symlink 不一致。"""
        if self._root is None:
            return False
        try:
            root_resolved = self._root.resolve()
            path_resolved = path.resolve()
            return path_resolved.parts[:len(root_resolved.parts)] == root_resolved.parts
        except (OSError, ValueError):
            return False


# ── 精簡沙箱執行器 ───────────────────────────────────────────────────────────
# 不直接依賴 mcp_server 的 Config/WorkspaceHandle，用標準 os 操作。

def _validate_rel_path(rel_path: str) -> list[str]:
    """驗證相對路徑並分割。"""
    if not rel_path:
        raise ValueError("empty path")
    if rel_path.startswith("/"):
        raise ValueError("absolute path not allowed")
    if "\0" in rel_path:
        raise ValueError("path contains NUL byte")
    parts = rel_path.split("/")
    for part in parts:
        if not part or part == "." or part == "..":
            raise ValueError(f"invalid path component: {part}")
    return parts


def _atomic_write_file(target_abs: Path, content: str) -> int:
    """原子寫入：暫存檔 + rename，全程 O_NOFOLLOW。"""
    data = content.encode("utf-8")
    if len(data) > 1024 * 1024:
        raise ValueError("content exceeds 1MB")
    tmp_name = target_abs.parent / f".{target_abs.name}.tmp.{uuid.uuid4().hex[:8]}"
    try:
        fd = os.open(str(tmp_name), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.rename(str(tmp_name), str(target_abs))
        return len(data)
    finally:
        try:
            tmp_name.unlink(missing_ok=True)
        except OSError:
            pass


def _execute_compute_draft(payload: dict) -> dict:
    """Containable compute_draft execution with zero side effects."""
    source = payload.get("content") or payload.get("prompt") or payload.get("command") or ""
    if not isinstance(source, str):
        source = str(source)
    source = source.strip()
    if not source:
        return {"status": "error", "error": "empty compute input"}

    lines = [line for line in source.splitlines() if line.strip()]
    return {
        "status": "ok",
        "stdout": "compute_draft analyzed input",
        "draft_summary": {
            "chars": len(source),
            "lines": len(lines),
            "words": len(source.split()),
            "digest": hashlib.sha256(source.encode("utf-8")).hexdigest()[:16],
        },
    }


def _execute_file_write(root: Path, rel_path: str, content: str) -> dict:
    """沙箱內檔案寫入。回執行結果 dict。"""
    try:
        parts = _validate_rel_path(rel_path)
    except ValueError as e:
        return {"status": "blocked", "error": str(e)}
    target = root.joinpath(*parts)
    if not target.resolve().absolute().parts[:len(root.parts)] == root.parts:
        return {"status": "blocked", "error": "path escape detected"}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        written = _atomic_write_file(target, content)
        return {"status": "ok", "bytes": written, "path": rel_path}
    except (OSError, ValueError) as e:
        return {"status": "error", "error": str(e)}


def _execute_file_delete(root: Path, rel_path: str) -> dict:
    """沙箱內檔案刪除。"""
    try:
        parts = _validate_rel_path(rel_path)
    except ValueError as e:
        return {"status": "blocked", "error": str(e)}
    target = root.joinpath(*parts)
    if not target.resolve().absolute().parts[:len(root.parts)] == root.parts:
        return {"status": "blocked", "error": "path escape detected"}
    try:
        if not target.exists():
            return {"status": "not_found", "error": f"path not found: {rel_path}"}
        if target.is_symlink():
            return {"status": "blocked", "error": "target is a symlink"}
        if not target.is_file():
            return {"status": "blocked", "error": "target is not a regular file"}
        target.unlink()
        return {"status": "ok", "path": rel_path}
    except OSError as e:
        return {"status": "error", "error": str(e)}


def _execute_pytest(root: Path, rel_path: str) -> dict:
    """沙箱內跑 pytest。回客觀訊號。"""
    parts = _validate_rel_path(rel_path)
    target = root.joinpath(*parts)
    if not target.exists():
        return {"status": "error", "error": f"pytest target not found: {rel_path}"}
    try:
        import subprocess
        result = subprocess.run(
            ["python3", "-m", "pytest", str(target), "-v", "--tb=short"],
            capture_output=True, text=True, timeout=60, cwd=str(root),
        )
        passed = result.returncode == 0
        return {
            "status": "ok" if passed else "failed",
            "pytest_passed": passed,
            "returncode": result.returncode,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
        }
    except FileNotFoundError:
        return {"status": "error", "error": "pytest not found"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "pytest timed out"}


# ── 合法/非法檢查 ────────────────────────────────────────────────────────────

_FOREVER_DENY_PATTERNS = [
    ".env", ".env.*", "secret*", "token*", "credentials*",
    "*.key", "*.pem", "id_rsa", "id_ed25519",
]

_RESTRICTED_EXTENSIONS = {".pyc", ".pyo", ".so", ".dylib", ".exe", ".dll"}

_FOREVER_DENY_CONTENT = [
    b"BEGIN RSA PRIVATE KEY",
    b"BEGIN OPENSSH PRIVATE KEY",
    b"ghp_",  # GitHub token 啟發式
    b"sk-",   # API key 啟發式
]


def _is_path_legal(rel_path: str) -> tuple[bool, str]:
    """檢查路徑是否合法（不被永遠拒絕規則擋住）。"""
    import fnmatch
    for pattern in _FOREVER_DENY_PATTERNS:
        if fnmatch.fnmatch(rel_path, pattern):
            return False, f"forever_denied pattern: {pattern}"
    ext = Path(rel_path).suffix.lower()
    if ext in _RESTRICTED_EXTENSIONS:
        return False, f"restricted extension: {ext}"
    return True, ""


def _is_content_legal(data: bytes) -> tuple[bool, str]:
    """檢查內容是否含有永遠拒絕的機密模式。"""
    for pattern in _FOREVER_DENY_CONTENT:
        if pattern in data:
            return False, f"content contains denied pattern"
    return True, ""


def _compute_digest(action_id: str, result: dict) -> str:
    """計算 digest（hash + 截斷 redact，不落全文）。"""
    raw = f"{action_id}:{result.get('status', 'unknown')}:{time.time()}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"sha256:{h}"


# ── 主 canary 執行器 ──────────────────────────────────────────────────────────


def canary_execute(
    request: ActionRequest,
    sandbox_dir: str | Path | None = None,
    signal_callback: Callable[[dict], None] | None = None,
) -> VerdictV2:
    """沙箱 canary 執行器。

    流程：
    1. 裁判覆核 reversible_actual（不信自報）
    2. escaping → 直接 gate=escalate，不執行
    3. containable → checkpoint → 真跑 → 檢查合法 → commit/rollback
    4. 產 VerdictV2
    5. 餵 process_verdict 更新 ratchet

    Args:
        request: ActionRequest（來自 neuralis bridge）
        sandbox_dir: 沙箱基礎目錄（預設系統 temp）
        signal_callback: 可選的客觀訊號回呼（如 pytest 結果）
    """
    # ── 1. 裁判覆核 ───────────────────────────────────────────────────
    actual = classify_reversibility(request.task_class)
    verdict = VerdictV2(action_id=request.action_id, source="sandbox-canary")

    # ── 2. escaping → escalate ─────────────────────────────────────────
    if actual == "escaping":
        verdict.lane = "human"
        verdict.outcome = "fail"
        verdict.reversible_actual = "escaping"
        verdict.status = "escalate"
        verdict.feedback = f"task_class={request.task_class} is escaping — cannot execute in sandbox"
        verdict.gate = {"decision": "escalate", "reason": "escaping task class, not executable in sandbox"}
        verdict.digest = _compute_digest(request.action_id, {"status": "escalated"})
        verdict.committed = False
        verdict.passed = False
        verdict.score = 0.0
        # 餵 process_verdict（不 committed，不會更新 ratchet）
        process_verdict(request, verdict)
        return verdict

    # ── 3. 解析 payload + 從 registry 解析 operation ────────────────────
    payload = request.payload or {}
    operation = resolve_operation(request.task_class, payload)
    if operation not in SUPPORTED_OPERATIONS:
        verdict.lane = "human"
        verdict.outcome = "fail"
        verdict.reversible_actual = "containable"
        verdict.feedback = f"unsupported operation: {operation}"
        verdict.gate = {"decision": "escalate", "reason": f"operation {operation} not in sandbox canary"}
        verdict.digest = _compute_digest(request.action_id, {"status": "unsupported_op"})
        process_verdict(request, verdict)
        return verdict

    rel_path = payload.get("path", "")
    content = payload.get("content", "")

    requires_path = operation in {"write_file", "delete_file", "pytest"}
    if requires_path:
        # ── 路徑合法檢查 ────────────────────────────────────────────────
        path_legal, legal_reason = _is_path_legal(rel_path)
        if not path_legal:
            verdict.lane = "deny"
            verdict.outcome = "fail"
            verdict.reversible_actual = "containable"
            verdict.feedback = f"illegal path: {legal_reason}"
            verdict.gate = {"decision": "deny", "reason": legal_reason}
            verdict.digest = _compute_digest(request.action_id, {"status": "denied", "reason": legal_reason})
            verdict.committed = False
            process_verdict(request, verdict)
            return verdict

    check_content = operation in {"write_file", "compute"}
    if check_content:
        # ── 內容合法檢查 ────────────────────────────────────────────────
        content_legal, content_reason = _is_content_legal(content.encode("utf-8"))
        if not content_legal:
            verdict.lane = "deny"
            verdict.outcome = "fail"
            verdict.reversible_actual = "containable"
            verdict.feedback = f"illegal content: {content_reason}"
            verdict.gate = {"decision": "deny", "reason": content_reason}
            verdict.digest = _compute_digest(request.action_id, {"status": "denied", "reason": content_reason})
            verdict.committed = False
            process_verdict(request, verdict)
            return verdict

    # ── 4. 建立沙箱 workspace + 快照 checkpoint ─────────────────────────
    ws = SandboxWorkspace(sandbox_dir)
    root = ws.start()

    try:
        # 內建 checkpoint：快照目標檔案（如果存在）
        snapshot_dir = root / ".canary-snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        ckpt_id = uuid.uuid4().hex[:12]
        ckpt_meta = {"id": ckpt_id, "paths": {}, "created_at": time.time()}

        if rel_path:
            target_abs = root / rel_path
            if target_abs.exists() and target_abs.is_file() and not target_abs.is_symlink():
                ckpt_data = target_abs.read_bytes()
                ckpt_meta["paths"][rel_path] = {
                    "content_b64": ckpt_data.hex()[:100],  # 只存 hash 夠 rollback
                    "size": len(ckpt_data),
                    "exists": True,
                }
                # 存完整備份到 .canary-snapshots
                backup_path = snapshot_dir / f"{ckpt_id}_{rel_path.replace('/', '_')}.bak"
                backup_path.write_bytes(ckpt_data)
                ckpt_meta["paths"][rel_path]["backup"] = str(backup_path)

        # ── 5. 真跑動作 ──────────────────────────────────────────────────
        if operation == "write_file":
            exec_result = _execute_file_write(root, rel_path, content)
        elif operation == "delete_file":
            exec_result = _execute_file_delete(root, rel_path)
        elif operation == "pytest":
            exec_result = _execute_pytest(root, rel_path)
        elif operation == "compute":
            exec_result = _execute_compute_draft(payload)
        else:
            exec_result = {"status": "error", "error": f"unsupported: {operation}"}

        # ── 6. 收集客觀訊號 ─────────────────────────────────────────────
        objective_signal: dict[str, Any] = {"operation": operation, "result_status": exec_result.get("status", "")}
        if operation == "pytest":
            objective_signal["kind"] = "pytest"
            objective_signal["detail"] = exec_result.get("stdout", "")[:500]
            objective_signal["pytest_passed"] = exec_result.get("pytest_passed", False)
            if signal_callback:
                signal_callback(objective_signal)
        else:
            objective_signal["kind"] = "goal_met"
            objective_signal["detail"] = exec_result.get("stdout", "")[:500]

        # ── 7. 裁判判決：合法→commit / 非法→rollback ──────────────────
        legal = exec_result.get("status") == "ok"

        if legal:
            # commit：保持檔案狀態，清 checkpoint
            for path_info in ckpt_meta.get("paths", {}).values():
                bp = path_info.get("backup")
                if bp:
                    try:
                        Path(bp).unlink(missing_ok=True)
                    except OSError:
                        pass
            committed = True
            gate_decision = "allow"
            gate_reason = f"{operation} completed successfully in sandbox"
            outcome = "pass"
            passed = True
            score = 1.0
        else:
            # rollback：還原 checkpoint
            try:
                restored = 0
                for rel_p, path_info in ckpt_meta.get("paths", {}).items():
                    bp = path_info.get("backup")
                    if bp and Path(bp).exists():
                        target_abs = root / rel_p
                        target_abs.write_bytes(Path(bp).read_bytes())
                        restored += 1
                        Path(bp).unlink(missing_ok=True)
            except Exception as e:
                restored = -1
            committed = False
            gate_decision = "deny"
            gate_reason = f"{operation} failed: {exec_result.get('error', exec_result.get('status', 'unknown'))}; rollback={'applied' if restored >= 0 else 'failed'}"
            outcome = "fail"
            passed = False
            score = 0.0

        # ── 8. 建 VerdictV2 ──────────────────────────────────────────────
        cost_actual = {"tokens": 0, "compute": 1}
        verdict = VerdictV2(
            action_id=request.action_id,
            status="pass" if outcome == "pass" else "retry",
            score=score,
            feedback=f"canary: lane=sandbox operation={operation} result={exec_result.get('status')}",
            passed=passed,
            source="sandbox-canary",
            violations=[],
            lane="sandbox",
            outcome=outcome,
            reversible_actual="containable",
            objective_signal=objective_signal,
            cost_actual=cost_actual,
            committed=committed,
            gate={"decision": gate_decision, "reason": gate_reason},
            digest=_compute_digest(request.action_id, exec_result),
        )

    except Exception as e:
        verdict = VerdictV2(
            action_id=request.action_id,
            status="retry",
            score=0.0,
            feedback=f"canary internal error: {e}",
            passed=False,
            source="sandbox-canary",
            lane="human",
            outcome="error",
            reversible_actual="containable",
            gate={"decision": "escalate", "reason": f"canary error: {e}"},
            digest=_compute_digest(request.action_id, {"status": "internal_error"}),
        )
    finally:
        ws.cleanup()

    # ── 9. 餵 process_verdict 更新 ratchet ──────────────────────────────
    try:
        process_verdict(request, verdict)
    except Exception:
        pass  # best-effort

    return verdict
