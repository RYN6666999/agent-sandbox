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
}


ALIASES: list[str] = list(_MODEL_PARAMS.keys())


def resolve(alias: str) -> dict:
    """Return litellm.completion kwargs for a logical model alias."""
    return _MODEL_PARAMS.get(alias, {"model": alias})
