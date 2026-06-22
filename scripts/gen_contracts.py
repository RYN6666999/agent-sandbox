"""
Generates contracts/<action>.py from MODEL_BODIES defined in this file.

Single source of truth: MODEL_BODIES (this file). It is what gets generated.
openspec/specs/*.spec.md are DESCRIPTIVE intent docs (human-readable
input/success/error/examples), not the generator input. They describe why a
contract looks the way it does; they do not drive code generation.

To change a contract: edit MODEL_BODIES here, then re-run this script.
Update the matching .spec.md when intent changes, so the prose stays honest.
Never hand-edit contracts/ (regenerated) and never treat .spec.md as the
generator's input (it isn't parsed).
"""
import json
import re
import sys
from pathlib import Path

SPECS_DIR = Path(__file__).parent.parent / "openspec" / "specs"
CONTRACTS_DIR = Path(__file__).parent.parent / "contracts"

REQUIRED_SECTIONS = {"input", "success", "error", "examples"}

# Map spec action names → Python class names
CLASS_NAMES = {
    "task_spec": "TaskSpec",
    "interface_contract": "InterfaceContract",
    "routing_triple": "RoutingTriple",
    "dept_output": "DeptOutput",
}

# Hardcoded Pydantic model bodies derived from specs (single source read at gen time)
MODEL_BODIES = {
    "task_spec": """\
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
""",

    "interface_contract": """\
from pydantic import BaseModel, field_validator, model_validator
from typing import Any

class InterfaceContract(BaseModel):
    producer: str
    consumer: str
    schema: dict[str, Any]
    version: str = "1.0.0"

    @field_validator("producer", "consumer")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v

    @field_validator("schema")
    @classmethod
    def schema_is_dict(cls, v) -> dict:
        if not isinstance(v, dict):
            raise ValueError("schema must be a dict")
        return v

    @model_validator(mode="after")
    def producer_ne_consumer(self) -> "InterfaceContract":
        if self.producer == self.consumer:
            raise ValueError("producer and consumer must differ")
        return self
""",

    "routing_triple": """\
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
""",

    "dept_output": """\
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
""",
}


def parse_sections(text: str) -> dict[str, str]:
    sections = {}
    current = None
    buf = []
    for line in text.splitlines():
        m = re.match(r"^## (.+)", line)
        if m:
            if current:
                sections[current] = "\n".join(buf).strip()
            current = m.group(1).strip()
            buf = []
        else:
            buf.append(line)
    if current:
        sections[current] = "\n".join(buf).strip()
    return sections


def parse_frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.+?)\n---", text, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def validate_spec(path: Path, sections: dict, fm: dict) -> list[str]:
    errors = []
    missing = REQUIRED_SECTIONS - set(sections.keys())
    if missing:
        errors.append(f"missing sections: {missing}")
    for required in ("domain", "action", "version"):
        if required not in fm:
            errors.append(f"frontmatter missing: {required}")
    return errors


def gen_contract(action: str) -> str:
    body = MODEL_BODIES.get(action)
    if not body:
        raise ValueError(f"No model body defined for action: {action}")
    header = f'"""Auto-generated from openspec/specs/{action}.spec.md — do not hand-edit."""\n'
    return header + body


def main():
    CONTRACTS_DIR.mkdir(exist_ok=True)
    (CONTRACTS_DIR / "__init__.py").touch()

    errors_found = False
    for spec_path in sorted(SPECS_DIR.glob("*.spec.md")):
        text = spec_path.read_text()
        fm = parse_frontmatter(text)
        sections = parse_sections(text)
        action = fm.get("action", spec_path.stem.replace(".spec", ""))

        errs = validate_spec(spec_path, sections, fm)
        if errs:
            print(f"✗ {spec_path.name}: {errs}")
            errors_found = True
            continue

        out_path = CONTRACTS_DIR / f"{action}.py"
        out_path.write_text(gen_contract(action))
        print(f"✓ generated contracts/{action}.py")

    if errors_found:
        sys.exit(1)


if __name__ == "__main__":
    main()
