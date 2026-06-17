"""Auto-generated from openspec/specs/interface_contract.spec.md — do not hand-edit."""
from pydantic import BaseModel, field_validator, model_validator
from typing import Any

class InterfaceContract(BaseModel):
    producer: str
    consumer: str
    output_schema: dict[str, Any]
    version: str = "1.0.0"

    @field_validator("producer", "consumer")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v

    @field_validator("output_schema")
    @classmethod
    def output_schema_is_dict(cls, v) -> dict:
        if not isinstance(v, dict):
            raise ValueError("schema must be a dict")
        return v

    @model_validator(mode="after")
    def producer_ne_consumer(self) -> "InterfaceContract":
        if self.producer == self.consumer:
            raise ValueError("producer and consumer must differ")
        return self
