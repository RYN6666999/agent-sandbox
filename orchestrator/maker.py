"""Maker: produces output from TaskSpec. Uses router to pick model + skills."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import litellm
import requests
from typing import Callable
from contracts.task_spec import TaskSpec
from router import route
from router.skill_injector import build_system_prompt
from orchestrator.model_registry import resolve as _resolve

BASE_PROMPT = (
    "You are a focused implementer. Produce exactly what is asked. "
    "No extra commentary unless the task requires it."
)

SETTINGS_PATH = Path(__file__).parent.parent / "data" / "settings.json"


def _load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text())
        except Exception:
            pass
    return {}


def _call_mcp_tool(server_url: str, tool_name: str, args: dict) -> str:
    """Call an MCP tool via JSON-RPC 2.0."""
    try:
        resp = requests.post(
            server_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": tool_name, "arguments": args}},
            timeout=15,
        )
        data = resp.json()
        result = data.get("result", {})
        # MCP returns content array
        content = result.get("content", [])
        if isinstance(content, list):
            return "\n".join(
                c.get("text", "") for c in content if c.get("type") == "text"
            )
        return str(result)
    except Exception as e:
        return f"[MCP error: {e}]"


def _list_mcp_tools(server_url: str) -> list[dict]:
    """List tools from an MCP server (JSON-RPC tools/list)."""
    try:
        resp = requests.post(
            server_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            timeout=10,
        )
        data = resp.json()
        return data.get("result", {}).get("tools", [])
    except Exception:
        return []


def _mcp_tools_to_litellm(tools: list[dict]) -> list[dict]:
    """Convert MCP tool defs to LiteLLM function-calling format."""
    out = []
    for t in tools:
        schema = t.get("inputSchema", {})
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": schema,
            },
        })
    return out


def _make_via_claude_code(spec: TaskSpec, feedback: str, round_n: int,
                          on_token: "Callable[[str], None] | None") -> str:
    """Run task via `claude --print` subprocess (uses Pro subscription + all Claude Code tools)."""
    claude_bin = shutil.which("claude")
    if not claude_bin:
        raise RuntimeError("claude CLI not found on PATH — run `npm install -g @anthropic-ai/claude-code`")

    prompt_parts = [f"Task: {spec.why}"]
    if spec.taste:
        prompt_parts.append(f"Requirements: {'; '.join(spec.taste)}")
    if spec.boundaries:
        prompt_parts.append(f"Do NOT: {'; '.join(spec.boundaries)}")
    if feedback and round_n > 1:
        prompt_parts.append(f"\nPrevious attempt feedback (round {round_n}):\n{feedback}")

    prompt = "\n".join(prompt_parts)

    result = subprocess.run(
        [claude_bin, "--print", "-p", prompt,
         "--output-format", "text", "--model", "claude-sonnet-4-6"],
        capture_output=True, text=True, timeout=300,
    )
    output = (result.stdout or result.stderr or "").strip()
    if on_token and output:
        on_token(output)
    return output


def make(spec: TaskSpec, feedback: str = "", round_n: int = 1,
         on_token: "Callable[[str], None] | None" = None,
         request_id: str | None = None,
         session_id: str | None = None) -> str:
    """Call the routed model and return raw output string."""
    if spec.executor == "claude-code":
        return _make_via_claude_code(spec, feedback, round_n, on_token)

    settings = _load_settings()

    policy_result = route(spec.why, request_id=request_id, session_id=session_id, round_n=round_n)
    triple = policy_result.triple

    # D17/D15 fix: settings["maker_model"] overrides mapping-table hardcode.
    # triple still provides skills and mcp_tools; only model is overridden.
    maker_model_alias = settings.get("maker_model") or triple.model

    # Build system prompt — inject user system_prompt if set
    base = BASE_PROMPT
    user_sys = settings.get("system_prompt", "").strip()
    if user_sys:
        base = f"{BASE_PROMPT}\n\n{user_sys}"

    system = build_system_prompt(triple.skills, maker_model_alias, base)
    user_msg = _build_user_msg(spec, feedback, round_n)

    params = _resolve(maker_model_alias)
    max_tokens = settings.get("max_tokens", 2048)
    temperature = settings.get("temperature", None)
    if temperature is not None:
        params["temperature"] = temperature

    # Collect enabled MCP servers and their tools
    mcp_servers = [s for s in settings.get("mcp_servers", []) if s.get("enabled")]
    all_tools: list[dict] = []
    tool_server_map: dict[str, str] = {}  # tool_name → server_url

    for srv in mcp_servers:
        url = srv.get("url", "")
        if not url:
            continue
        tools = _list_mcp_tools(url)
        litellm_tools = _mcp_tools_to_litellm(tools)
        for t in litellm_tools:
            tool_name = t["function"]["name"]
            tool_server_map[tool_name] = url
        all_tools.extend(litellm_tools)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]

    # Agentic tool-calling loop (max 5 rounds to prevent infinite)
    for _ in range(5):
        call_kwargs: dict = dict(messages=messages, max_tokens=max_tokens, **params)
        if all_tools:
            call_kwargs["tools"] = all_tools
            call_kwargs["tool_choice"] = "auto"

        if on_token is not None and not all_tools:
            # Streaming only when no tools (tool calls need full response)
            chunks: list[str] = []
            try:
                stream = litellm.completion(stream=True, **call_kwargs)
                for chunk in stream:
                    delta = chunk.choices[0].delta.content or ""
                    if delta:
                        chunks.append(delta)
                        on_token(delta)
                return "".join(chunks)
            except Exception:
                if chunks:
                    return "".join(chunks)
                raise

        response = litellm.completion(**call_kwargs)
        msg = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        if finish_reason != "tool_calls" or not getattr(msg, "tool_calls", None):
            text = msg.content or ""
            if on_token and text:
                on_token(text)
            return text

        # Execute tool calls and add results to messages
        messages.append(msg.model_dump() if hasattr(msg, "model_dump") else {
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
        })

        for tc in msg.tool_calls:
            fn = tc.function
            try:
                args = json.loads(fn.arguments)
            except Exception:
                args = {}
            server_url = tool_server_map.get(fn.name, "")
            result = _call_mcp_tool(server_url, fn.name, args) if server_url else f"[no server for {fn.name}]"
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    # Fallback: one more call without tools
    response = litellm.completion(messages=messages, max_tokens=max_tokens, **params)
    return response.choices[0].message.content or ""


def _build_user_msg(spec: TaskSpec, feedback: str, round_n: int) -> str:
    parts = [
        f"Task: {spec.why}",
        f"Input: {spec.io_example.get('input', '')}",
        f"Expected output shape: {spec.io_example.get('expected_output', '')}",
    ]
    if spec.taste:
        parts.append(f"Quality signals: {'; '.join(spec.taste)}")
    if spec.boundaries:
        parts.append(f"Red lines: {'; '.join(spec.boundaries)}")
    if feedback and round_n > 1:
        parts.append(f"\n[Round {round_n} — Checker feedback]\n{feedback}")
    return "\n".join(parts)
