"""檔案快照 — 明確 allow-path 清單 + 永久拒絕規則。

只接受 regular file。傳入 directory 直接拒絕。
"""

import fnmatch
import hashlib
import json
import os
import stat
import tarfile
import time
import uuid
from pathlib import Path

_FOREVER_DENY = [
    ".env", ".env.*", "**/.env", "**/.env.*",
    "secret*", "**/secret*",
    "token*", "**/token*",
    "credentials*", "**/credentials*",
    "*.key", "**/*.key",
    "*.pem", "**/*.pem",
    "id_rsa", "id_ed25519",
]


def _is_forever_denied(rel_path: str) -> bool:
    for pattern in _FOREVER_DENY:
        if fnmatch.fnmatch(rel_path, pattern):
            return True
    return False


class Checkpoint:
    def __init__(self, checkpoint_id: str, work_dir: Path, snapshot_dir: Path,
                 allow_paths: list[str]) -> None:
        self.id = checkpoint_id
        self.work_dir = work_dir
        self.snapshot_dir = snapshot_dir
        self.allow_paths = allow_paths
        self.meta_path = snapshot_dir / f"{checkpoint_id}.json"
        self.archive_path = snapshot_dir / f"{checkpoint_id}.tar.gz"

    @classmethod
    def create(cls, work_dir: Path, snapshot_dir: Path,
               allow_paths: list[str] | None = None) -> "Checkpoint":
        if not allow_paths:
            raise ValueError("checkpoint requires explicit allow_paths")
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        ckpt_id = uuid.uuid4().hex[:12]
        ckpt = cls(ckpt_id, work_dir, snapshot_dir, allow_paths)

        file_hashes: dict[str, str] = {}
        for rel_path in allow_paths:
            Checkpoint._validate_allow_path(rel_path, work_dir)
            if _is_forever_denied(rel_path):
                raise ValueError(f"forever_denied: {rel_path}")
            abs_path = work_dir / rel_path
            if not abs_path.exists():
                continue
            st = abs_path.stat()
            file_hashes[rel_path] = _sha256(abs_path)
            file_hashes[f"__meta__{rel_path}"] = json.dumps({
                "mode": st.st_mode, "size": st.st_size,
            })

        meta = {
            "id": ckpt_id, "created_at": time.time(), "work_dir": str(work_dir),
            "allow_paths": allow_paths,
            "file_count": len([k for k in file_hashes if not k.startswith("__meta__")]),
            "file_hashes": file_hashes,
        }
        ckpt.meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        os.chmod(ckpt.meta_path, 0o600)

        with tarfile.open(ckpt.archive_path, "w:gz") as tar:
            for rel_path in allow_paths:
                if _is_forever_denied(rel_path):
                    continue
                abs_path = work_dir / rel_path
                if abs_path.exists():
                    tar.add(abs_path, arcname=rel_path)
        os.chmod(ckpt.archive_path, 0o600)
        return ckpt

    @staticmethod
    def _validate_allow_path(rel_path: str, work_dir: Path) -> None:
        """驗證 allow_path 是 regular file，不是 directory。"""
        if not rel_path:
            raise ValueError("empty allow_path")
        if rel_path.startswith("/"):
            raise ValueError("absolute allow_path not allowed")
        if ".." in rel_path.split("/"):
            raise ValueError("allow_path contains '..'")
        if "\0" in rel_path:
            raise ValueError("allow_path contains NUL")
        abs_path = work_dir / rel_path
        if abs_path.is_dir():
            raise ValueError(f"not a regular file: {rel_path}")

    def restore(self) -> dict:
        if not self.archive_path.exists():
            return {"status": "error", "error": "archive not found"}
        meta = json.loads(self.meta_path.read_text())
        changes = []
        restored_count = 0
        for rel_path in meta["allow_paths"]:
            if _is_forever_denied(rel_path):
                continue
            abs_path = self.work_dir / rel_path
            orig_hash = meta["file_hashes"].get(rel_path, "")
            curr_hash = _sha256(abs_path) if abs_path.exists() else ""
            if curr_hash != orig_hash:
                changes.append(f"restore: {rel_path}")
                restored_count += 1
        if restored_count > 0:
            with tarfile.open(self.archive_path, "r:gz") as tar:
                tar.extractall(path=self.work_dir)
        for rel_path in meta["allow_paths"]:
            orig_hash = meta["file_hashes"].get(rel_path, "")
            if not orig_hash:
                abs_path = self.work_dir / rel_path
                if abs_path.exists():
                    abs_path.unlink()
                    changes.append(f"delete new: {rel_path}")
        for rel_path in meta["allow_paths"]:
            mk = f"__meta__{rel_path}"
            if mk in meta["file_hashes"]:
                try:
                    md = json.loads(meta["file_hashes"][mk])
                    abs_path = self.work_dir / rel_path
                    if abs_path.exists():
                        cm = stat.S_IMODE(abs_path.stat().st_mode)
                        em = stat.S_IMODE(md["mode"])
                        if cm != em:
                            abs_path.chmod(em)
                except Exception:
                    pass
        self._cleanup()
        return {"status": "ok", "restored_count": restored_count, "changes": changes}

    def _cleanup(self) -> None:
        try:
            self.meta_path.unlink(missing_ok=True)
            self.archive_path.unlink(missing_ok=True)
        except OSError:
            pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def cleanup_expired(snapshot_dir: Path, ttl_seconds: int = 86400) -> int:
    if not snapshot_dir.exists():
        return 0
    now = time.time()
    removed = 0
    for f in snapshot_dir.iterdir():
        if f.name.endswith(".tar.gz") or f.name.endswith(".json"):
            if not f.is_file():
                continue
            try:
                if now - f.stat().st_mtime > ttl_seconds:
                    f.unlink()
                    removed += 1
            except OSError:
                continue
    return removed