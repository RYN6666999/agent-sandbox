"""Executor registry — maps logical names to CLI executors, provides uniform run()."""
import json
import shutil
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Callable

SETTINGS_PATH = Path(__file__).parent.parent / "data" / "settings.json"

# In-memory registry
_registry: dict[str, dict[str, Any]] = {}

# Built-in executors (merged with settings.json overrides on module load)
_BUILTIN_EXECUTORS: dict[str, dict[str, Any]] = {
    "claude-code": {
        "name": "claude-code",
        "binary": "claude",
        "flags": ["--print", "--output-format", "text"],
        "prompt_flag": "-p",
        "model_flag": "--model",
        "default_model": "claude-sonnet-4-6",
        "timeout": 300,
        "type": "subprocess",
    },
}


def _load_settings_overrides() -> dict[str, dict[str, Any]]:
    """Load executors section from settings.json, if present."""
    try:
        data = json.loads(SETTINGS_PATH.read_text())
        return data.get("executors", {})
    except Exception:
        return {}


def _init():
    """Merge built-in defaults with settings.json overrides."""
    overrides = _load_settings_overrides()
    for name, builtin in _BUILTIN_EXECUTORS.items():
        entry = builtin.copy()
        if name in overrides:
            entry.update(overrides[name])
        _registry[name] = entry


def register(defn: dict[str, Any]) -> None:
    """Register an executor definition."""
    name = defn.get("name", "")
    if not name:
        raise ValueError("ExecutorDef must have a 'name' field")
    _registry[name] = defn


def get(name: str) -> dict[str, Any] | None:
    """Look up an executor by name."""
    return _registry.get(name)


def list_all() -> list[dict[str, Any]]:
    """Return all registered executors."""
    return list(_registry.values())


def run(name: str, prompt: str, *, timeout: int | None = None,
        on_token: Callable[[str], None] | None = None) -> str:
    """Spawn executor CLI, pass prompt, return stdout."""
    defn = _registry.get(name)
    if not defn:
        raise KeyError(f"Executor '{name}' not registered")

    binary = defn.get("binary", "")
    if not binary:
        raise ValueError(f"Executor '{name}' has no 'binary' field")

    bin_path = shutil.which(binary) or binary
    effective_timeout = timeout or defn.get("timeout", 300)

    exec_type = defn.get("type", "subprocess")

    if exec_type == "super-engine-warm":
        # Warm daemon: HTTP POST to a persistent server (keeps browser alive)
        port = defn.get("daemon_port", 3456)
        payload = json.dumps({
            "provider": defn.get("daemon_provider", "gemini"),
            "prompt": prompt,
        }).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/ask",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=effective_timeout)
            data = json.loads(resp.read())
            output = data.get("output", data.get("error", ""))
            if on_token and output:
                on_token(output)
            return output
        except urllib.error.URLError as e:
            return f"[daemon error: {e.reason if hasattr(e, 'reason') else str(e)}]"
        except Exception as e:
            return f"[daemon error: {e}]"

    if exec_type == "super-engine":
        # super-engine: binary + args + prompt appended as last arg
        # (args should include --prompt or equivalent flag if needed)
        cmd = [bin_path] + list(defn.get("args", []))
        cmd.append(prompt)
    else:
        # subprocess (default): binary + flags + [prompt_flag, prompt] + model_spec
        cmd = [bin_path] + list(defn.get("flags", []))

        prompt_flag = defn.get("prompt_flag")
        if prompt_flag:
            cmd += [prompt_flag, prompt]
        else:
            cmd.append(prompt)

        model_flag = defn.get("model_flag")
        default_model = defn.get("default_model")
        if model_flag and default_model:
            cmd += [model_flag, default_model]

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=effective_timeout,
    )

    output = (result.stdout or result.stderr or "").strip()
    if on_token and output:
        on_token(output)
    return output


# Initialize on module import
_init()