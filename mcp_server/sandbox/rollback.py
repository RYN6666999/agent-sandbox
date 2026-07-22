"""失敗自動/手動恢復 — 從 checkpoint 還原檔案狀態。"""

from pathlib import Path

from .checkpoint import Checkpoint


def auto_rollback(checkpoint_id: str, snapshot_dir: Path) -> dict:
    """自動回退到指定 checkpoint。

    Returns:
        {"status": "ok"|"error", "restored_count": int, "error": str?}
    """
    try:
        meta_path = snapshot_dir / f"{checkpoint_id}.json"
        if not meta_path.exists():
            return {"status": "error", "error": f"checkpoint {checkpoint_id} not found"}

        work_dir = _resolve_work_dir(meta_path, snapshot_dir)
        ckpt = Checkpoint(checkpoint_id, work_dir, snapshot_dir)
        count = ckpt.restore()
        return {"status": "ok", "restored_count": count}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def manual_rollback(checkpoint_id: str, snapshot_dir: Path) -> dict:
    """手動回退到指定 checkpoint。"""
    return auto_rollback(checkpoint_id, snapshot_dir)


def _resolve_work_dir(meta_path: Path, snapshot_dir: Path) -> Path:
    import json
    meta = json.loads(meta_path.read_text())
    return Path(meta.get("work_dir", snapshot_dir.parent))