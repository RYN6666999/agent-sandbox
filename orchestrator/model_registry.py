"""Logical model alias → LiteLLM completion kwargs. No imports from this project."""
import os
from dotenv import load_dotenv
load_dotenv()

_MODEL_PARAMS: dict[str, dict] = {
    # ── 免費 (OpenRouter free tier) ──────────────────────────────────────
    "gpt-oss-120b": {
        "model": "openrouter/openai/gpt-oss-120b",
        "api_key": os.environ.get("OPENROUTER_API_KEY", ""),
        "free": True,
    },
    "deepseek-v3": {
        "model": "openrouter/deepseek/deepseek-chat",
        "api_key": os.environ.get("OPENROUTER_API_KEY", ""),
        "free": True,
    },
    "deepseek-v4-flash": {
        "model": "openrouter/deepseek/deepseek-v4-flash",
        "api_key": os.environ.get("OPENROUTER_API_KEY", ""),
        "free": False,
    },
    "openrouter-classifier": {
        "model": "openrouter/openai/gpt-oss-120b",
        "api_key": os.environ.get("OPENROUTER_API_KEY", ""),
        "free": True,
    },
    # ── 付費 ─────────────────────────────────────────────────────────────
    "claude-opus": {
        "model": "openrouter/anthropic/claude-opus-4-5",
        "api_key": os.environ.get("OPENROUTER_API_KEY", ""),
        "free": False,
    },
    "claude-sonnet": {
        "model": "anthropic/claude-sonnet-4-5",
        "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "free": False,
    },
    "gemini-flash": {
        "model": "gemini/gemini-2.0-flash",
        "api_key": os.environ.get("GEMINI_API_KEY", ""),
        "free": False,
    },
    "agnes": {
        "model": "openai/agnes-2.0-flash",
        "api_key": os.environ.get("AGNES_API_KEY", ""),
        "api_base": "https://apihub.agnes-ai.com/v1",
        "free": False,
    },
    "agnes-image": {
        "model": "openai/agnes-image-2.1-flash",
        "api_key": os.environ.get("AGNES_API_KEY", ""),
        "api_base": "https://apihub.agnes-ai.com/v1",
        "free": False,
    },
    "agnes-video": {
        "model": "openai/agnes-video-v2.0",
        "api_key": os.environ.get("AGNES_API_KEY", ""),
        "api_base": "https://apihub.agnes-ai.com/v1",
        "free": False,
    },
}

ALIASES: list[str] = list(_MODEL_PARAMS.keys())
FREE_MODELS: list[str] = [k for k, v in _MODEL_PARAMS.items() if v.get("free")]
PAID_MODELS: list[str] = [k for k, v in _MODEL_PARAMS.items() if not v.get("free")]


def resolve(alias: str) -> dict:
    """Return litellm.completion kwargs for a logical alias or raw model string.

    Priority:
    1. Known alias in _MODEL_PARAMS → return registered params (excludes internal 'free' flag).
    2. String starts with "openrouter/" → inject OPENROUTER_API_KEY automatically.
    3. Any other string → pass through as-is (LiteLLM handles provider prefix routing).
    """
    if alias in _MODEL_PARAMS:
        params = dict(_MODEL_PARAMS[alias])
        params.pop("free", None)
        return params
    if alias.startswith("openrouter/"):
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            raise ValueError("OPENROUTER_API_KEY not set — cannot use OpenRouter model")
        return {"model": alias, "api_key": key}
    # raw LiteLLM model string
    return {"model": alias}
