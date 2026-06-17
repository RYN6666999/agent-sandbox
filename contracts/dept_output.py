"""Auto-generated from openspec/specs/dept_output.spec.md — do not hand-edit."""
from pydantic import BaseModel, field_validator
from typing import Any, Literal

class DeptOutput(BaseModel):
    dept: str
    artifacts: list[dict[str, Any]]
    status: Literal["done", "blocked"]
    contract_ref: str

    @field_validator("dept", "contract_ref")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v
