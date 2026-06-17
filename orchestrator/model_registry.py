"""Logical model alias → LiteLLM completion kwargs. No imports from this project."""
import os
from dotenv import load_dotenv
load_dotenv()

_MODEL_PARAMS: dict[str, dict] = {
    "agnes": {
        "model": "openai/agnes-2.0-flash",
        "api_key": os.environ.get("AGNES_API_KEY", ""),
        "api_base": "https://apihub.agnes-ai.com/v1",
    },
    "gemini-flash": {
        "model": "gemini/gemini-2.0-flash",
        "api_key": os.environ.get("GEMINI_API_KEY", ""),
    },
    "claude-sonnet": {
        "model": "anthropic/claude-sonnet-4-5",
        "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
    },
    "ollama-local": {
        "model": "ollama/mistral",
        "api_base": "http://localhost:11434",
    },
    # dev-period classifier: calibrated routing intent, free tier on OpenRouter
    "openrouter-classifier": {
        "model": "openrouter/openai/gpt-oss-120b",
        "api_key": os.environ.get("OPENROUTER_API_KEY", ""),
    },
}

ALIASES: list[str] = list(_MODEL_PARAMS.keys())


def resolve(alias: str) -> dict:
    """Return litellm.completion kwargs for a logical alias or raw model string.

    Priority:
    1. Known alias in _MODEL_PARAMS → return registered params (includes api_key / api_base).
    2. String starts with "openrouter/" → inject OPENROUTER_API_KEY automatically.
    3. Any other string → pass through as-is (LiteLLM handles provider prefix routing).
    """
    if alias in _MODEL_PARAMS:
        return dict(_MODEL_PARAMS[alias])
    if alias.startswith("openrouter/"):
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            raise ValueError("OPENROUTER_API_KEY not set — cannot use OpenRouter model")
        return {"model": alias, "api_key": key}
    # raw LiteLLM model string (e.g. "anthropic/claude-opus-4-8", "gemini/gemini-2.0-flash")
    return {"model": alias}
