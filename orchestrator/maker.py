"""Maker: produces output from TaskSpec. Routes through executor_registry
with a litellm fallback for the default path.

In the new architecture, Scream is Planner+Maker:
  1. Scream plans → POST /task/make (this function)
  2. AgentOS routes through executor_registry or calls litellm
  3. Returns output → Scream decides next step (verify / retry / deliver)

No internal loop/retry logic — Scream controls iteration externally.
"""
import json
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import litellm
from contracts.task_spec import TaskSpec
from orchestrator import executor_registry
from orchestrator import decision_log
from orchestrator.model_registry import resolve as _resolve
from router import route
from router.skill_injector import build_system_prompt

SETTINGS_PATH = Path(__file__).parent.parent / "data" / "settings.json"

_BASE_PROMPT = (
    "You are a focused implementer. Produce exactly what is asked. "
    "No extra commentary unless the task requires it."
)


def _load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text())
        except Exception:
            pass
    return {}


def make(spec: TaskSpec, *, on_token: Callable[[str], None] | None = None,
         request_id: str | None = None,
         session_id: str | None = None) -> str:
    """One-shot LLM call. Routes through executor_registry for non-litellm executors."""
    executor = spec.executor or "litellm"

    # Route registered executors through executor_registry
    if executor != "litellm" and executor_registry.get(executor):
        prompt = _build_prompt(spec, executor)
        _record_maker_event(request_id, session_id, executor, spec.why[:200])
        return executor_registry.run(executor, prompt, timeout=300, on_token=on_token)

    # Default litellm path
    _record_maker_event(request_id, session_id, "litellm", spec.why[:200])
    return _call_litellm(spec, on_token=on_token, request_id=request_id, session_id=session_id)


def _build_prompt(spec: TaskSpec, executor: str = "litellm") -> str:
    """Build prompt string for non-litellm executors."""
    parts = [f"Task: {spec.why}"]
    if spec.io_example.get("expected_output"):
        parts.append(f"Expected output: {spec.io_example['expected_output']}")
    if spec.taste:
        parts.append(f"Requirements: {'; '.join(spec.taste)}")
    if spec.boundaries:
        parts.append(f"Do NOT: {'; '.join(spec.boundaries)}")
    return "\n".join(parts)


def _call_litellm(spec: TaskSpec, *,
                  on_token: Callable[[str], None] | None = None,
                  request_id: str | None = None,
                  session_id: str | None = None) -> str:
    """Call litellm with routing, skill injection, and streaming support."""
    settings = _load_settings()
    maker_model_alias = settings.get("maker_model", "")

    # Route through routing pipeline
    policy_result = route(spec.why, request_id=request_id, session_id=session_id, round_n=1)
    triple = policy_result.triple
    model_alias = maker_model_alias or triple.model

    base = _BASE_PROMPT
    user_sys = settings.get("system_prompt", "").strip()
    if user_sys:
        base = f"{_BASE_PROMPT}\n\n{user_sys}"

    system = build_system_prompt(triple.skills, model_alias, base)
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": _build_prompt(spec, "litellm")}]

    params = _resolve(model_alias)
    max_tokens = settings.get("max_tokens", 2048)
    temperature = settings.get("temperature", None)
    if temperature is not None:
        params["temperature"] = temperature

    if on_token:
        chunks: list[str] = []
        try:
            stream = litellm.completion(stream=True, messages=messages,
                                        max_tokens=max_tokens, **params)
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    chunks.append(delta)
                    on_token(delta)
            return "".join(chunks)
        except Exception:
            if chunks:
                return "".join(chunks)
            raise

    response = litellm.completion(messages=messages, max_tokens=max_tokens, **params)
    return response.choices[0].message.content or ""


def _record_maker_event(request_id: str | None, session_id: str | None,
                        executor: str, task_preview: str) -> None:
    if not request_id:
        return
    decision_log.record_execution_route(
        request_id=request_id,
        session_id=session_id or request_id,
        round_n=1,
        decision=f"maker_{executor}",
        decision_source="maker",
        matched_keyword=None, confidence=None,
        classifier_model=None, fallback_reason=None,
        pre_policy_model=None, pre_policy_skills=None, pre_policy_tools=None,
        final_model=executor, final_skills=None, final_tools=None,
        policy_applied=False, policy_changed=False,
        requires_human_confirm=False, violations=None,
        details={"executor": executor, "task_preview": task_preview},
    )
