"""失敗自動/手動恢復 — 從 checkpoint 還原檔案狀態。"""

import json
from pathlib import Path

from .checkpoint import Checkpoint


def auto_rollback(checkpoint_id: str, snapshot_dir: Path) -> dict:
    """自動回退到指定 checkpoint。

    allow_paths 從 checkpoint meta 讀回 — Checkpoint.__init__ 要求它，
    且 restore() 只還原 meta 裡列出的路徑。

    Returns:
        {"status": "ok", "restored_count": int, "changes": list[str]}
        或 {"status": "error", "error": str}
    """
    try:
        meta_path = snapshot_dir / f"{checkpoint_id}.json"
        if not meta_path.exists():
            return {"status": "error", "error": f"checkpoint {checkpoint_id} not found"}

        meta = json.loads(meta_path.read_text())
        work_dir = Path(meta.get("work_dir", snapshot_dir.parent))
        allow_paths = meta.get("allow_paths", [])
        ckpt = Checkpoint(checkpoint_id, work_dir, snapshot_dir, allow_paths)
        return ckpt.restore()
    except Exception as e:
        return {"status": "error", "error": str(e)}


def manual_rollback(checkpoint_id: str, snapshot_dir: Path) -> dict:
    """手動回退到指定 checkpoint。"""
    return auto_rollback(checkpoint_id, snapshot_dir)
