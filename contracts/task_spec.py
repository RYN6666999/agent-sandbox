"""Auto-generated from openspec/specs/task_spec.spec.md — do not hand-edit."""
from pydantic import BaseModel, field_validator
from typing import Any

class TaskSpec(BaseModel):
    why: str
    io_example: dict[str, Any]
    taste: list[str]
    boundaries: list[str]
    # stop conditions (set during align phase)
    stop_on_metric: str = ""
    max_rounds: int = 5
    executor: str = "litellm"   # "litellm" | "claude-code" | "web-llm-genspark" | "web-llm-gemini"

    @field_validator("why")
    @classmethod
    def why_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("why must not be empty")
        return v

    @field_validator("io_example")
    @classmethod
    def io_has_expected(cls, v: dict) -> dict:
        if "expected_output" not in v:
            raise ValueError("io_example must contain expected_output")
        return v
