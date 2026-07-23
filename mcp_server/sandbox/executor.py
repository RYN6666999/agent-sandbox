"""沙盒執行器 — fd-relative 安全路徑開啟 + operation dispatch。

使用 WorkspaceHandle 持久 root_fd，每次 operation 只 dup 不重新開啟。

唯讀操作（不產 checkpoint）：
- list_directory, read_file, get_cwd

寫入操作（動作前必產 checkpoint，失敗自動 rollback）：
- write_file, delete_file
"""

import os
import stat
import time
import errno
import uuid
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
from .checkpoint import Checkpoint
from .rollback import auto_rollback


# ── 白名單操作 ──────────────────────────────────────────────

READONLY_OPS = frozenset({
    "list_directory", "read_file", "get_cwd",
})

WRITE_OPS = frozenset({
    "write_file", "delete_file",
})

ALLOWED_OPS = READONLY_OPS | WRITE_OPS

# 寫入內容上限，與 read_file 的讀取上限一致
MAX_WRITE_BYTES = 1024 * 1024


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


def _stat_target(dup_root_fd: int, path_parts: list[str]) -> Optional[os.stat_result]:
    """fd-relative lstat 目標檔案，**不跟隨 symlink**。不存在回 None。

    寫入前必須先跑這個：checkpoint 用一般路徑操作建快照，`_sha256()` 會跟隨
    symlink 去讀 workspace 外的檔案。先在這裡擋掉 symlink，checkpoint 才不會
    對 workspace 外的目標動作。
    """
    dir_parts = path_parts[:-1]
    filename = path_parts[-1]

    parent_fd, opened_fds = _fd_walk(dup_root_fd, dir_parts)
    try:
        try:
            return os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
    finally:
        for fd in opened_fds:
            if fd != dup_root_fd:
                try:
                    os.close(fd)
                except OSError:
                    pass


def _execute_write_file(dup_root_fd: int, path_parts: list[str], content: str) -> int:
    """fd-relative 原子寫入：同目錄暫存檔 + rename。

    先寫暫存檔再 rename，原檔在 rename 成功前不被截斷；寫到一半失敗
    （磁碟滿、程序中斷）不會留下半截檔案。暫存檔以 O_EXCL 建立，
    全程 O_NOFOLLOW。

    Returns:
        實際寫入的位元組數
    """
    data = content.encode("utf-8")
    if len(data) > MAX_WRITE_BYTES:
        raise ValueError(f"content exceeds {MAX_WRITE_BYTES} bytes")

    dir_parts = path_parts[:-1]
    filename = path_parts[-1]

    parent_fd, opened_fds = _fd_walk(dup_root_fd, dir_parts)
    tmp_name = f".{filename}.tmp.{uuid.uuid4().hex[:8]}"
    tmp_live = False
    try:
        tmp_fd = os.open(
            tmp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        tmp_live = True
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        os.rename(tmp_name, filename, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        tmp_live = False
        return len(data)
    finally:
        if tmp_live:
            try:
                os.unlink(tmp_name, dir_fd=parent_fd)
            except OSError:
                pass
        for fd in opened_fds:
            if fd != dup_root_fd:
                try:
                    os.close(fd)
                except OSError:
                    pass


def _execute_delete_file(dup_root_fd: int, path_parts: list[str]) -> None:
    """fd-relative 刪除檔案。unlink 不跟隨 symlink（刪的是 entry 本身）。"""
    dir_parts = path_parts[:-1]
    filename = path_parts[-1]

    parent_fd, opened_fds = _fd_walk(dup_root_fd, dir_parts)
    try:
        os.unlink(filename, dir_fd=parent_fd)
    finally:
        for fd in opened_fds:
            if fd != dup_root_fd:
                try:
                    os.close(fd)
                except OSError:
                    pass


def _classify_error(e: Exception) -> tuple[str, str]:
    """把例外歸類成 result status。與唯讀分支的既有慣例一致。"""
    if isinstance(e, FileNotFoundError):
        return "not_found", str(e)
    if isinstance(e, (PermissionError, ValueError)):
        return "blocked", str(e)
    if isinstance(e, OSError):
        if e.errno in (errno.ELOOP, errno.ENOTDIR, errno.EACCES, errno.EISDIR):
            return "blocked", str(e)
        return "error", str(e)
    return "error", str(e)


def _do_write_file(
    dup_root_fd: int,
    path_parts: list[str],
    op_path: str,
    content: str,
    config: Config,
    result: dict,
) -> None:
    """write_file 完整流程：symlink 檢查 → checkpoint → 寫入 → 失敗回退。

    三步順序不可調換：
    1. symlink 檢查要在 checkpoint 之前 — Checkpoint 用一般路徑操作，
       `_sha256()` 會跟隨 symlink 讀到 workspace 外的檔案。
    2. checkpoint 要在寫入之前 — 否則沒有可還原的狀態。
    3. 寫入失敗一律嘗試 rollback，並把結果誠實回報在 rollback_applied。
    """
    # 1. 目標必須不存在，或是 regular file
    try:
        st = _stat_target(dup_root_fd, path_parts)
    except Exception as e:
        result["status"], result["stderr"] = _classify_error(e)
        if result["status"] == "not_found":
            result["stderr"] = f"path not found: {op_path}"
        return

    if st is not None:
        if stat.S_ISLNK(st.st_mode):
            result["status"] = "blocked"
            result["stderr"] = "target is a symlink"
            return
        if not stat.S_ISREG(st.st_mode):
            result["status"] = "blocked"
            result["stderr"] = "target is not a regular file"
            return

    # 2. checkpoint。Checkpoint 的 forever-deny 清單（.env / secret* / *.key …）
    #    在這裡變成寫入保護：快照不了的路徑就不准寫。
    try:
        ckpt = Checkpoint.create(
            config.work_dir, config.snapshot_dir, allow_paths=[op_path]
        )
    except ValueError as e:
        result["status"] = "blocked"
        result["stderr"] = f"checkpoint refused: {e}"
        return
    except OSError as e:
        result["status"] = "error"
        result["stderr"] = f"checkpoint failed: {e}"
        return

    result["checkpoint_id"] = ckpt.id

    # 3. 寫入，失敗即回退
    try:
        written = _execute_write_file(dup_root_fd, path_parts, content)
    except Exception as e:
        rb = auto_rollback(ckpt.id, config.snapshot_dir)
        result["rollback_applied"] = rb.get("status") == "ok"
        result["status"], result["stderr"] = _classify_error(e)
        if not result["rollback_applied"]:
            result["stderr"] += f" | rollback failed: {rb.get('error')}"
        return

    result["status"] = "ok"
    result["stdout"] = f"wrote {written} bytes to {op_path}"


def _do_delete_file(
    dup_root_fd: int,
    path_parts: list[str],
    op_path: str,
    config: Config,
    result: dict,
) -> None:
    """delete_file 完整流程：存在性 + symlink 檢查 → checkpoint → unlink → 失敗回退。

    與 write_file 同一套安全順序，兩點不同：
    - 目標必須「已存在」（不存在回 not_found）— 刪不存在的東西不是靜默成功。
    - checkpoint 拍下待刪的檔，rollback 走 restore() 的「從 archive 解壓還原
      已消失的檔」分支。forever-deny 路徑快照不了 → 不准刪（無法回退）。
    """
    # 1. 目標必須存在、是 regular file、非 symlink
    try:
        st = _stat_target(dup_root_fd, path_parts)
    except Exception as e:
        result["status"], result["stderr"] = _classify_error(e)
        if result["status"] == "not_found":
            result["stderr"] = f"path not found: {op_path}"
        return

    if st is None:
        result["status"] = "not_found"
        result["stderr"] = f"path not found: {op_path}"
        return
    if stat.S_ISLNK(st.st_mode):
        result["status"] = "blocked"
        result["stderr"] = "target is a symlink"
        return
    if not stat.S_ISREG(st.st_mode):
        result["status"] = "blocked"
        result["stderr"] = "target is not a regular file"
        return

    # 2. checkpoint（拍下待刪的檔）
    try:
        ckpt = Checkpoint.create(
            config.work_dir, config.snapshot_dir, allow_paths=[op_path]
        )
    except ValueError as e:
        result["status"] = "blocked"
        result["stderr"] = f"checkpoint refused: {e}"
        return
    except OSError as e:
        result["status"] = "error"
        result["stderr"] = f"checkpoint failed: {e}"
        return

    result["checkpoint_id"] = ckpt.id

    # 3. 刪除，失敗即回退
    try:
        _execute_delete_file(dup_root_fd, path_parts)
    except Exception as e:
        rb = auto_rollback(ckpt.id, config.snapshot_dir)
        result["rollback_applied"] = rb.get("status") == "ok"
        result["status"], result["stderr"] = _classify_error(e)
        if not result["rollback_applied"]:
            result["stderr"] += f" | rollback failed: {rb.get('error')}"
        return

    result["status"] = "ok"
    result["stdout"] = f"deleted {op_path}"


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

    # 寫入操作必須有 path（不能落到「無 path」的分支靜默成功）
    if operation in WRITE_OPS and not op_path:
        result["status"] = "blocked"
        result["stderr"] = "path required for write operation"
        _write_audit(config, operation, session_id, result, start)
        return result

    # 路徑驗證
    path_parts = []
    if op_path and operation in ("read_file", "list_directory", "write_file", "delete_file"):
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

        elif operation == "write_file":
            _do_write_file(
                dup_root_fd, path_parts, op_path,
                params.get("content", ""), config, result,
            )

        elif operation == "delete_file":
            _do_delete_file(dup_root_fd, path_parts, op_path, config, result)

    finally:
        try:
            os.close(dup_root_fd)
        except OSError:
            pass

    # Audit
    _write_audit(config, operation, session_id, result, start)
    return result