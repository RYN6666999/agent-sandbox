"""Contract validation tests. All invalid inputs must raise ValidationError."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from pydantic import ValidationError

from contracts.task_spec import TaskSpec
from contracts.interface_contract import InterfaceContract
from contracts.routing_triple import RoutingTriple
from contracts.dept_output import DeptOutput


# --- TaskSpec ---

def test_task_spec_valid():
    t = TaskSpec(
        why="build cashflow calculator",
        io_example={"input": "rent=30000", "expected_output": "cashflow=9000"},
        taste=["show breakdown"],
        boundaries=["no tax"],
    )
    assert t.why == "build cashflow calculator"


def test_task_spec_empty_why():
    with pytest.raises(ValidationError):
        TaskSpec(why="", io_example={"input": "x", "expected_output": "y"}, taste=[], boundaries=[])


def test_task_spec_whitespace_why():
    with pytest.raises(ValidationError):
        TaskSpec(why="   ", io_example={"input": "x", "expected_output": "y"}, taste=[], boundaries=[])


def test_task_spec_missing_expected_output():
    with pytest.raises(ValidationError):
        TaskSpec(why="do x", io_example={"input": "x"}, taste=[], boundaries=[])


def test_task_spec_taste_not_list():
    with pytest.raises(ValidationError):
        TaskSpec(why="do x", io_example={"input": "x", "expected_output": "y"}, taste="not a list", boundaries=[])


# --- InterfaceContract ---

def test_interface_contract_valid():
    c = InterfaceContract(
        producer="backend",
        consumer="frontend",
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
    )
    assert c.producer == "backend"


def test_interface_contract_empty_producer():
    with pytest.raises(ValidationError):
        InterfaceContract(producer="", consumer="frontend", output_schema={})


def test_interface_contract_empty_consumer():
    with pytest.raises(ValidationError):
        InterfaceContract(producer="backend", consumer="", output_schema={})


def test_interface_contract_same_producer_consumer():
    with pytest.raises(ValidationError):
        InterfaceContract(producer="backend", consumer="backend", output_schema={})


def test_interface_contract_schema_not_dict():
    with pytest.raises(ValidationError):
        InterfaceContract(producer="backend", consumer="frontend", output_schema="not a dict")


# --- RoutingTriple ---

def test_routing_triple_valid():
    r = RoutingTriple(model="agnes", skills=["ponytail"], mcp_tools=[], confidence=0.8)
    assert r.confidence == 0.8


def test_routing_triple_empty_model():
    with pytest.raises(ValidationError):
        RoutingTriple(model="", skills=[], mcp_tools=[], confidence=0.5)


def test_routing_triple_confidence_too_high():
    with pytest.raises(ValidationError):
        RoutingTriple(model="agnes", skills=[], mcp_tools=[], confidence=1.5)


def test_routing_triple_confidence_negative():
    with pytest.raises(ValidationError):
        RoutingTriple(model="agnes", skills=[], mcp_tools=[], confidence=-0.1)


# --- DeptOutput ---

def test_dept_output_valid():
    d = DeptOutput(
        dept="backend",
        artifacts=[{"type": "code", "path": "main.py"}],
        status="done",
        contract_ref="backend->frontend@1.0.0",
    )
    assert d.status == "done"


def test_dept_output_invalid_status():
    with pytest.raises(ValidationError):
        DeptOutput(dept="backend", artifacts=[], status="shipped", contract_ref="x->y@1")


def test_dept_output_empty_dept():
    with pytest.raises(ValidationError):
        DeptOutput(dept="", artifacts=[], status="done", contract_ref="x->y@1")


def test_dept_output_empty_contract_ref():
    with pytest.raises(ValidationError):
        DeptOutput(dept="backend", artifacts=[], status="done", contract_ref="")
