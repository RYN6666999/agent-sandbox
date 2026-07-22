"""沙盒執行器 — fd-relative 安全路徑開啟 + operation dispatch。

使用 WorkspaceHandle 持久 root_fd，每次 operation 只 dup 不重新開啟。
支援白名單操作（唯讀，不產 checkpoint）：
- list_directory, read_file, get_cwd
"""

import os
import stat
import time
import errno
from pathlib import Path
from typing import Optional

from ..config import Config
from ..gate.audit import write_audit as _raw_audit

def _write_audit(config, operation, session_id, result, start):
    _raw_audit(config.audit_path, {
        "event": "sandbox_execute",
        "session_id": session_id,
        "operation": operation,
        "status": result["status"],
        "duration_ms": (time.time() - start) * 1000,
    })
from .workspace import WorkspaceHandle, WorkspaceIdentityChanged


# ── 白名單操作 ──────────────────────────────────────────────

ALLOWED_OPS = frozenset({
    "list_directory", "read_file", "get_cwd",
})


# ── fd-relative 路徑驗證 ──────────────────────────────────

def _validate_user_path(user_path: str) -> list[str]:
    """驗證並分割使用者提供的相對路徑。"""
    if not user_path:
        raise ValueError("empty path")
    if user_path.startswith("/"):
        raise ValueError("absolute path not allowed")
    if user_path.startswith("-"):
        raise ValueError("path starts with option prefix")
    if "\0" in user_path:
        raise ValueError("path contains NUL byte")
    _SHELL_METACHARS = frozenset(";&|`$<>()[]{}!\\'\"\n\t ")
    if any(c in user_path for c in _SHELL_METACHARS):
        raise ValueError("path contains shell metacharacters")

    parts = user_path.split("/")
    for part in parts:
        if not part:
            raise ValueError("empty path component")
        if part == ".":
            raise ValueError("path contains '.' component")
        if part == "..":
            raise ValueError("path contains '..' component")
        if "\0" in part:
            raise ValueError("path component contains NUL byte")
    return parts


def _fd_walk(dup_root_fd: int, parts: list[str]) -> tuple[int, list[int]]:
    """逐層 fd-relative 走到最後一層目錄。

    Returns:
        (parent_fd, opened_fds) — parent_fd 是最後一層目錄的 fd
    """
    current_fd = dup_root_fd
    opened_fds = [current_fd]
    try:
        for part in parts:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current_fd)
            opened_fds.append(next_fd)
            st = os.fstat(next_fd)
            if not stat.S_ISDIR(st.st_mode):
                raise PermissionError(f"not a directory: {part}")
            if current_fd != dup_root_fd:
                os.close(current_fd)
                opened_fds.remove(current_fd)
            current_fd = next_fd
        return current_fd, opened_fds
    except:
        for fd in opened_fds:
            if fd != dup_root_fd:
                try:
                    os.close(fd)
                except OSError:
                    pass
        raise


def _execute_read_file(dup_root_fd: int, path_parts: list[str]) -> str:
    """fd-relative 讀取檔案。"""
    dir_parts = path_parts[:-1]
    filename = path_parts[-1]

    parent_fd, opened_fds = _fd_walk(dup_root_fd, dir_parts)
    try:
        file_fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        opened_fds.append(file_fd)
        st = os.fstat(file_fd)
        if not stat.S_ISREG(st.st_mode):
            raise PermissionError("not a regular file")

        with os.fdopen(file_fd, "r") as f:
            content = f.read(1024 * 1024)
        opened_fds.remove(file_fd)  # fdopen 接管了

        for fd in opened_fds:
            if fd != dup_root_fd:
                try:
                    os.close(fd)
                except OSError:
                    pass
        return content
    except:
        for fd in opened_fds:
            if fd != dup_root_fd:
                try:
                    os.close(fd)
                except OSError:
                    pass
        raise


def _execute_list_directory(dup_root_fd: int, path_parts: list[str]) -> list[str]:
    """fd-relative 列出目錄內容。"""
    if not path_parts:
        return sorted(os.listdir(dup_root_fd))

    target_fd, opened_fds = _fd_walk(dup_root_fd, path_parts)
    try:
        entries = sorted(os.listdir(target_fd))
        for fd in opened_fds:
            if fd != dup_root_fd:
                try:
                    os.close(fd)
                except OSError:
                    pass
        return entries
    except:
        for fd in opened_fds:
            if fd != dup_root_fd:
                try:
                    os.close(fd)
                except OSError:
                    pass
        raise


# ── 主執行函式 ──────────────────────────────────────────────

def execute(
    operation: str,
    wh: WorkspaceHandle,
    config: Config,
    params: dict | None = None,
    session_id: str = "default",
) -> dict:
    """沙盒執行白名單操作。

    Args:
        operation: 白名單操作名稱
        wh: WorkspaceHandle（持久 root_fd）
        config: AgentOS 設定
        params: 操作參數 {"path": "..."}
        session_id: 工作階段 ID

    Returns:
        結構化結果 dict
    """
    start = time.time()
    params = params or {}
    op_path = params.get("path", "")

    result = {"status": "error", "stdout": "", "stderr": "", "checkpoint_id": None, "rollback_applied": False}

    # 操作合法性
    if operation not in ALLOWED_OPS:
        result["status"] = "blocked"
        result["stderr"] = f"operation not allowed: {operation}"
        _write_audit(config, operation, session_id, result, start)
        return result

    # 路徑驗證
    path_parts = []
    if op_path and operation in ("read_file", "list_directory"):
        try:
            path_parts = _validate_user_path(op_path)
        except ValueError as e:
            result["status"] = "blocked"
            result["stderr"] = str(e)
            _write_audit(config, operation, session_id, result, start)
            return result

    # 取得 dup root_fd（含 identity 驗證）
    try:
        dup_root_fd = wh.dup_fd()
    except WorkspaceIdentityChanged as e:
        result["status"] = "blocked"
        result["stderr"] = f"workspace_identity_changed: {e}"
        _write_audit(config, operation, session_id, result, start)
        return result

    try:
        if operation == "read_file":
            if not path_parts:
                result["status"] = "blocked"
                result["stderr"] = "path required"
            else:
                try:
                    content = _execute_read_file(dup_root_fd, path_parts)
                    result["status"] = "ok"
                    result["stdout"] = content
                except FileNotFoundError:
                    result["status"] = "not_found"
                    result["stderr"] = f"path not found: {op_path}"
                except PermissionError as e:
                    result["status"] = "blocked"
                    result["stderr"] = str(e)
                except OSError as e:
                    err = e.errno
                    if err in (errno.ELOOP, errno.ENOTDIR, errno.EACCES):
                        result["status"] = "blocked"
                        result["stderr"] = str(e)
                    else:
                        result["status"] = "error"
                        result["stderr"] = str(e)

        elif operation == "list_directory":
            try:
                entries = _execute_list_directory(dup_root_fd, path_parts)
                result["status"] = "ok"
                result["stdout"] = "\n".join(entries)
            except FileNotFoundError:
                result["status"] = "not_found"
                result["stderr"] = f"path not found: {op_path}"
            except PermissionError as e:
                result["status"] = "blocked"
                result["stderr"] = str(e)
            except OSError as e:
                err = e.errno
                if err in (errno.ELOOP, errno.ENOTDIR, errno.EACCES):
                    result["status"] = "blocked"
                    result["stderr"] = str(e)
                else:
                    result["status"] = "error"
                    result["stderr"] = str(e)

        elif operation == "get_cwd":
            result["status"] = "ok"
            result["stdout"] = wh.root_path

    finally:
        try:
            os.close(dup_root_fd)
        except OSError:
            pass

    # Audit
    _write_audit(config, operation, session_id, result, start)
    return result