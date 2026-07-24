"""Verdict v2 — 疊加 delta 欄位到既有 verdict dict。

既有 verdict dict（from orchestrator/loop.py）：
  {"status": "pass"|"retry"|"escalate", "score": float, "feedback": str,
   "passed": bool, "source": str, "violations": list}

VerdictV2 保留所有既有欄位並加上 v2 delta 欄位。ActionRequest 為輸入訊息。
"""
from pydantic import BaseModel, field_validator, model_validator
from typing import Any, Literal
from datetime import datetime, timezone


class ActionRequest(BaseModel):
    """neuralis bridge → agent-sandbox：Aris 想做的動作。"""
    action_id: str
    task_class: str
    payload: dict[str, Any] = {}
    workspace: str = ""
    declared_reversibility: Literal["containable", "escaping"] = "escaping"
    cost_estimate: dict[str, int] = {}  # {"tokens"?: int, "compute"?: int}
    ts: str = ""

    @field_validator("action_id", "task_class")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v

    @model_validator(mode="after")
    def auto_ts(self) -> "ActionRequest":
        if not self.ts:
            self.ts = datetime.now(timezone.utc).isoformat()
        return self


class VerdictV2(BaseModel):
    """agent-sandbox → neuralis bridge：評分結果。

    保留既有 verdict 欄位（status/score/feedback/passed/source/violations）+
    疊加 v2 delta 欄位（lane/outcome/reversible_actual/objective_signal/
    cost_actual/committed/gate/digest/ts）。
    """
    # ── 既有欄位（from orchestrator/loop.py） ──────────────────────────────
    action_id: str
    status: Literal["pass", "retry", "escalate"] = "retry"
    score: float = 0.0
    feedback: str = ""
    passed: bool = False
    source: str = "scoring-router"
    violations: list[dict[str, Any]] = []

    # ── v2 delta 欄位 ──────────────────────────────────────────────────────
    lane: Literal["deny", "human", "sandbox", "auto"] = "human"
    outcome: Literal["pass", "fail", "error"] = "fail"
    reversible_actual: Literal["containable", "escaping"] = "escaping"
    objective_signal: dict[str, Any] = {}  # {"kind": "pytest"|"goal_met"|..., "detail": ...}
    cost_actual: dict[str, int] = {}       # {"tokens": int, "compute": int}
    committed: bool = False
    gate: dict[str, Any] = {}              # {"decision": "allow"|"deny"|"escalate", "reason": str}
    digest: str = ""                        # hash + 截斷 redact 頭，不落全文
    ts: str = ""

    @field_validator("action_id")
    @classmethod
    def action_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("action_id must not be empty")
        return v

    @model_validator(mode="after")
    def auto_ts(self) -> "VerdictV2":
        if not self.ts:
            self.ts = datetime.now(timezone.utc).isoformat()
        return self

    def to_legacy_dict(self) -> dict:
        """吐回與 orchestrator/loop.py 相容的 dict（既有欄位）。"""
        return {
            "status": self.status,
            "score": self.score,
            "feedback": self.feedback,
            "passed": self.passed,
            "source": self.source,
            "violations": self.violations,
        }
