"""Maker: produces output from TaskSpec. Uses router to pick model + skills."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import litellm
from typing import Callable
from contracts.task_spec import TaskSpec
from router import route
from router.skill_injector import build_system_prompt
from orchestrator.model_registry import resolve as _resolve

BASE_PROMPT = (
    "You are a focused implementer. Produce exactly what is asked. "
    "No extra commentary unless the task requires it."
)


def make(spec: TaskSpec, feedback: str = "", round_n: int = 1,
         on_token: "Callable[[str], None] | None" = None) -> str:
    """Call the routed model and return raw output string.
    on_token: called with each text chunk during streaming (optional).
    """
    policy_result = route(spec.why)
    triple = policy_result.triple

    system = build_system_prompt(triple.skills, triple.model, BASE_PROMPT)
    user_msg = _build_user_msg(spec, feedback, round_n)

    params = _resolve(triple.model)

    if on_token is not None:
        # streaming mode — fallback to full text if stream breaks mid-way
        chunks: list[str] = []
        try:
            stream = litellm.completion(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=2048,
                stream=True,
                **params,
            )
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
    else:
        response = litellm.completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=2048,
            **params,
        )
        return response.choices[0].message.content


def _build_user_msg(spec: TaskSpec, feedback: str, round_n: int) -> str:
    parts = [
        f"Task: {spec.why}",
        f"Input: {spec.io_example.get('input', '')}",
        f"Expected output shape: {spec.io_example.get('expected_output', '')}",
    ]
    if spec.taste:
        parts.append(f"Quality signals: {'; '.join(spec.taste)}")
    if spec.boundaries:
        parts.append(f"Red lines: {'; '.join(spec.boundaries)}")
    if feedback and round_n > 1:
        parts.append(f"\n[Round {round_n} — Checker feedback]\n{feedback}")
    return "\n".join(parts)
