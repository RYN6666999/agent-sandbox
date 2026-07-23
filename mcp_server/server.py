"""AgentOS MCP Server — FastMCP 入口。

MCP tool `sandbox_execute` 只接受結構化 operation + params。
使用 WorkspaceHandle 持久 root_fd。
未知參數在 tools/list schema 與 runtime 兩層都被拒絕（見 _harden_tool_args）。
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ValidationError
from typing import Optional

from .config import Config, ConfigError
from .sandbox.executor import execute, ALLOWED_OPS
from .sandbox.workspace import WorkspaceHandle, WorkspaceIdentityChanged


class SandboxExecuteArgs(BaseModel):
    """sandbox_execute 的輸入契約（欄位真值來源）。

    這個模型宣告 flat API 的合法欄位集合；實際擋下未知參數的是
    _harden_tool_args() 收緊過的 FastMCP arg model。兩者由
    _harden_tool_args 的欄位比對斷言保持同步。
    """
    model_config = {"extra": "forbid"}

    operation: str
    path: str = ""
    content: str = ""
    session_id: str = "default"

mcp = FastMCP(
    "AgentOS MCP Server",
    instructions="AgentOS 系統管家 — 安全沙盒執行層 (v0.2.2)",
)

_wh: WorkspaceHandle | None = None
_config: Config | None = None


@mcp.tool()
def sandbox_execute(
    operation: str,
    path: str = "",
    content: str = "",
    session_id: str = "default",
) -> dict:
    """在沙盒中執行白名單操作（fd-relative safe open）。

    唯讀操作：
    - list_directory(path) — 列出目錄內容
    - read_file(path) — 讀取檔案內容（O_NOFOLLOW + fd-relative）
    - get_cwd() — 回傳工作目錄路徑

    寫入操作（動作前自動 checkpoint，失敗自動回退）：
    - write_file(path, content) — 原子寫入（暫存檔 + rename），上限 1MB
    - delete_file(path) — 刪除 regular file，目標須存在

    Args:
        operation: 白名單操作名稱
        path: 操作目標相對路徑
        content: write_file 的內容；其他操作忽略
        session_id: 工作階段 ID

    Returns:
        {"status": "ok"|"blocked"|"error"|"not_found",
         "stdout": str, "stderr": str,
         "checkpoint_id": str|None, "rollback_applied": bool}
    """
    # 型別/取值再驗一次。未知參數已在 arg model 層擋掉，到不了這裡。
    try:
        SandboxExecuteArgs(
            operation=operation, path=path, content=content, session_id=session_id
        )
    except ValidationError as e:
        return {"status": "blocked", "stdout": "", "stderr": f"invalid arguments: {e}"}

    if _wh is None or _config is None:
        return {"status": "error", "stdout": "", "stderr": "server not initialized"}
    return execute(
        operation=operation,
        wh=_wh,
        config=_config,
        params={"path": path, "content": content},
        session_id=session_id,
    )


def _harden_tool_args(tool_name: str, contract: type[BaseModel]) -> dict:
    """把 FastMCP 自動產生的 arg model 收緊成 extra=forbid。

    為什麼需要這步：mcp 1.26.0 的 FastMCP 以
    `self._mcp_server.call_tool(validate_input=False)` 註冊 lowlevel handler，
    刻意跳過 lowlevel 的 jsonschema 檢查（向後相容）。因此 inputSchema 上寫
    additionalProperties 不會產生 runtime 效果，唯一真正跑驗證的是
    fn_metadata.arg_model。收緊這個 model 一次修好兩件事：

    1. model_json_schema() 產出帶 additionalProperties:false 的 inputSchema
       → tools/list 對外宣告正確。
    2. arg_model.model_validate() 對未知參數丟 ValidationError
       → 未知參數在進 executor 前就被擋下，回 isError。

    保持 flat API（operation / path / session_id），不改成巢狀 model 參數。
    走 _tool_manager 是這版唯一的取用路徑；版本漂移時下面的斷言會大聲失敗。
    """
    tool = mcp._tool_manager.get_tool(tool_name)
    if tool is None:
        raise RuntimeError(f"tool not registered: {tool_name}")

    arg_model = tool.fn_metadata.arg_model
    arg_model.model_config["extra"] = "forbid"
    arg_model.model_rebuild(force=True)
    tool.parameters = arg_model.model_json_schema(by_alias=True)

    # self-check：schema 真的收緊了，且欄位集合與宣告契約一致
    if tool.parameters.get("additionalProperties") is not False:
        raise RuntimeError(
            f"{tool_name}: additionalProperties 未生效，"
            f"FastMCP/pydantic 版本可能已變更"
        )
    if set(tool.parameters.get("properties", {})) != set(contract.model_fields):
        raise RuntimeError(
            f"{tool_name}: schema 欄位與 {contract.__name__} 不一致 "
            f"({sorted(tool.parameters.get('properties', {}))} vs "
            f"{sorted(contract.model_fields)})"
        )
    try:
        arg_model.model_validate({"operation": "get_cwd", "__probe__": 1})
    except ValidationError:
        pass
    else:
        raise RuntimeError(f"{tool_name}: arg model 仍接受未知參數")

    return tool.parameters


_harden_tool_args("sandbox_execute", SandboxExecuteArgs)


def main() -> None:
    import argparse
    global _config, _wh

    parser = argparse.ArgumentParser(description="AgentOS MCP Server")
    parser.add_argument("--serve", action="store_true", help="SSE 模式")
    parser.add_argument("--port", type=int, default=8001, help="SSE port")
    parser.add_argument("--config", type=str, help="agentos.json path")
    args = parser.parse_args()

    try:
        _config = Config(args.config)
        _wh = WorkspaceHandle(_config.work_dir)
    except (ConfigError, ValueError, OSError) as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.serve:
            mcp.run(transport="sse", port=args.port)
        else:
            mcp.run(transport="stdio")
    finally:
        if _wh:
            _wh.close()


if __name__ == "__main__":
    main()