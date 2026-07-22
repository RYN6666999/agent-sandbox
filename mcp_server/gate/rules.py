"""安全閘道 — 操作驗證。

驗證 operation + params 結構，拒絕 git_* 操作。
"""

from pathlib import Path

ALLOWED_OPS = frozenset({
    "list_directory", "read_file", "get_cwd",
})

_SHELL_METACHARS = frozenset(";&|`$<>()[]{}!\\'\"\n\t ")


def is_operation_allowed(operation: str, params: dict | None = None) -> tuple[bool, str]:
    if operation not in ALLOWED_OPS:
        return False, f"operation not allowed: {operation}"
    params = params or {}
    path = params.get("path", "")
    if path:
        if path.startswith("/"):
            return False, "absolute path not allowed"
        if path.startswith("-"):
            return False, "path starts with option prefix"
        if any(c in path for c in _SHELL_METACHARS):
            return False, "path contains shell metacharacters"
        if ".." in path.split("/"):
            return False, "path contains parent directory reference"
    return True, ""


def is_path_protected(path: str) -> bool:
    _PROTECTED_PATHS = [".env", ".ssh", "id_rsa", "id_ed25519"]
    resolved = Path(path).resolve()
    for frag in _PROTECTED_PATHS:
        if frag in str(resolved):
            return True
    return False