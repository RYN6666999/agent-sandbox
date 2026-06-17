"""Auto-generated from openspec/specs/routing_triple.spec.md — do not hand-edit."""
from pydantic import BaseModel, field_validator
from typing import Literal

class RoutingTriple(BaseModel):
    model: str
    skills: list[str]
    mcp_tools: list[str]
    confidence: float

    @field_validator("model")
    @classmethod
    def model_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("model must not be empty")
        return v

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")
        return v
