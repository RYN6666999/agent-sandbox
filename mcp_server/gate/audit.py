"""審計日誌 — JSONL 寫入。

所有透過 AgentOS MCP Server 執行的操作都會留下審計記錄。
"""

import json
import time
from pathlib import Path
from typing import Any


def write_audit(
    audit_path: Path,
    entry: dict[str, Any],
) -> None:
    """寫入一條審計記錄到 JSONL 檔案。

    Args:
        audit_path: 審計日誌檔案路徑
        entry: 審計記錄（dict），會自動加上 timestamp
    """
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **entry,
    }
    try:
        with open(audit_path, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 審計不應影響主流程


def read_audit(
    audit_path: Path,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """讀取審計日誌。

    Args:
        audit_path: 審計日誌檔案路徑
        limit: 最大回傳條數
        offset: 從檔案開頭跳過的行數

    Returns:
        審計記錄列表（最新在最後）
    """
    if not audit_path.exists():
        return []
    records: list[dict[str, Any]] = []
    with open(audit_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records[offset:][:limit]