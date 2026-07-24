"""設定載入 — 讀取 agentos.json + 環境變數。

AGENTOS_WORK_DIR 必須顯式設定，未設定或目錄不存在時拒絕啟動。
"""

import json
import os
import sys
from pathlib import Path
from typing import Any
from orchestrator.config_files import load_agentos_config

# ── 預設路徑 ──────────────────────────────────────────────

AGENTOS_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = AGENTOS_DIR / "agentos.json"
DEFAULT_AUDIT_PATH = AGENTOS_DIR / "mcp_server" / "audit.log"
DEFAULT_SNAPSHOT_DIR = AGENTOS_DIR / "mcp_server" / "snapshots"
DEFAULT_MCP_PORT = 8001


# ── 設定載入 ──────────────────────────────────────────────

class ConfigError(Exception):
    """設定錯誤，啟動時應拒絕。"""
    pass


class Config:
    """AgentOS MCP Server 設定。

    AGENTOS_WORK_DIR 必須顯式設定，否則 ConfigError。
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_CONFIG_PATH
        self._raw: dict[str, Any] = {}
        self._load()
        self._validate_work_dir()

    def _load(self) -> None:
        if not self.path.exists():
            self._raw = {"version": "0.0.0", "tools": {}}
            return
        self._raw = load_agentos_config()

    def _validate_work_dir(self) -> None:
        """AGENTOS_WORK_DIR 必須顯式設定，且必須是真實目錄（非 symlink）。"""
        raw = os.environ.get("AGENTOS_WORK_DIR", "")
        if not raw:
            raise ConfigError(
                "AGENTOS_WORK_DIR 未設定。MCP Server 需要顯式指定工作目錄，"
                "不得使用預設值。範例: AGENTOS_WORK_DIR=/path/to/workspace"
            )
        work_dir = Path(raw).resolve()
        if not work_dir.is_dir():
            raise ConfigError(
                f"AGENTOS_WORK_DIR={raw} 不存在或不是目錄"
            )
        # 檢查 work_dir 本身是否為 symlink
        if Path(raw).is_symlink():
            raise ConfigError(
                f"AGENTOS_WORK_DIR={raw} 是 symlink，不安全。請使用真實目錄路徑"
            )
        self._work_dir = work_dir

    @property
    def version(self) -> str:
        return self._raw.get("version", "0.0.0")

    @property
    def tools(self) -> dict[str, Any]:
        return self._raw.get("tools", {})

    @property
    def routes(self) -> dict[str, Any]:
        return self._raw.get("routes", {})

    @property
    def audit_path(self) -> Path:
        return Path(os.environ.get("AGENTOS_AUDIT_PATH", str(DEFAULT_AUDIT_PATH)))

    @property
    def snapshot_dir(self) -> Path:
        snap = os.environ.get("AGENTOS_SNAPSHOT_DIR", str(DEFAULT_SNAPSHOT_DIR))
        p = Path(snap)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def mcp_port(self) -> int:
        return int(os.environ.get("AGENTOS_MCP_PORT", str(DEFAULT_MCP_PORT)))

    @property
    def work_dir(self) -> Path:
        return self._work_dir

    def reload(self) -> None:
        self._load()

    def raw(self) -> dict[str, Any]:
        return self._raw