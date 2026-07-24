"""Canary adaptor registry.

Single source of truth for task_class -> sandbox operation mapping.
"""

from __future__ import annotations

from typing import Final


TASK_CLASS_TO_OPERATION: Final[dict[str, str]] = {
    # Containable classes — op_name 對應 sandbox_canary 的 _execute_* 函式
    "file_write": "write_file",
    "local_test": "pytest",
    "compute_draft": "compute",
    "refactor_local": "compute",
    "brief_draft": "compute",
    "gbrain_read": "compute",
}

SUPPORTED_OPERATIONS: Final[frozenset[str]] = frozenset({
    "write_file",
    "delete_file",
    "pytest",
    "compute",
})


def operation_for_task_class(task_class: str) -> str | None:
    return TASK_CLASS_TO_OPERATION.get(task_class)


def resolve_operation(task_class: str, payload: dict | None) -> str | None:
    """Resolve operation from payload override or task_class default mapping.

    Payload override is allowed only for known supported operations.
    """
    op = (payload or {}).get("operation")
    if isinstance(op, str) and op:
        return op
    return operation_for_task_class(task_class)


def has_task_mapping(task_class: str) -> bool:
    return task_class in TASK_CLASS_TO_OPERATION
