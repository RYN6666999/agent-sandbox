"""AgentOS action loop: routes a TaskSpec through the executor registry
with a litellm fallback.

v3 roles:
  - Scream (Plan+Execute) — calls LLM directly, writes code, judges delivery.
    Does NOT go through this AgentOS maker proxy.
  - Claude CLI — Checker only. Runs pytest + review, never writes code.
  - AgentOS — Pure action loop layer (zero-intelligence infrastructure).
    This function is the "route to executor" action within that loop.
  - Opus 4.8 (GenSpark) — Consultant, not a maker, not in the pipeline.
  - Gemini (super-engine) — Small helper.

No internal loop/retry logic — Scream controls iteration externally.
"""
import json
import sys
from dataclasses import dataclass, field
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

# DeepSeek V4 Flash 單價（USD per 1M tokens，供 runner 層累加使用）
PRICE_INPUT_PER_M = 0.09
PRICE_OUTPUT_PER_M = 0.18


@dataclass
class MakeResult:
    """make() 的回傳值。

    output     — 模型（或 executor）的文字輸出
    prompt_tokens     — 輸入 token 數；subprocess 路徑填 0
    completion_tokens — 輸出 token 數；subprocess 路徑填 0
    cost_usd   — 本次呼叫成本（USD）；根據 V4 Flash 單價計算
    cost_known — False 表示走 subprocess 路徑，無法取得真實 token，
                 runner 層不應將此次成本計入全局油表
    """
    output: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    cost_known: bool = True

    @classmethod
    def from_subprocess(cls, output: str) -> "MakeResult":
        """subprocess / executor_registry 路徑：token 未知，cost_known=False。"""
        return cls(output=output, prompt_tokens=0, completion_tokens=0,
                   cost_usd=0.0, cost_known=False)

    @classmethod
    def from_usage(cls, output: str, prompt_tokens: int, completion_tokens: int) -> "MakeResult":
        """litellm 路徑：用 V4 Flash 單價計算本次成本。"""
        cost = (prompt_tokens / 1_000_000 * PRICE_INPUT_PER_M
                + completion_tokens / 1_000_000 * PRICE_OUTPUT_PER_M)
        return cls(output=output, prompt_tokens=prompt_tokens,
                   completion_tokens=completion_tokens,
                   cost_usd=cost, cost_known=True)


def _load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text())
        except Exception:
            pass
    return {}


def make(spec: TaskSpec, *, on_token: Callable[[str], None] | None = None,
         request_id: str | None = None,
         session_id: str | None = None) -> MakeResult:
    """AgentOS route-to-executor action. Routes through executor_registry for non-litellm executors.
        In v3, Scream calls LLM directly — this is AgentOS's own action loop routing, not a maker proxy.

    Returns MakeResult (output + usage + cost).  cost_known=False on subprocess paths.
    """
    executor = spec.executor or "litellm"

    # Route registered executors through executor_registry
    if executor != "litellm" and executor_registry.get(executor):
        prompt = _build_prompt(spec, executor)
        _record_maker_event(request_id, session_id, executor, spec.why[:200])
        raw = executor_registry.run(executor, prompt, timeout=300, on_token=on_token)
        return MakeResult.from_subprocess(raw)

    # Default litellm path — but maker_model from settings may be an executor
    settings = _load_settings()
    maker_model = settings.get("maker_model", "")
    if maker_model and executor_registry.get(maker_model):
        prompt = _build_prompt(spec, maker_model)
        _record_maker_event(request_id, session_id, maker_model, spec.why[:200])
        raw = executor_registry.run(maker_model, prompt, timeout=300, on_token=on_token)
        return MakeResult.from_subprocess(raw)

    _record_maker_event(request_id, session_id, "litellm", spec.why[:200])
    return _call_litellm(spec, settings=settings, on_token=on_token, request_id=request_id, session_id=session_id)


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
                  settings: dict | None = None,
                  on_token: Callable[[str], None] | None = None,
                  request_id: str | None = None,
                  session_id: str | None = None) -> MakeResult:
    """Call litellm with routing, skill injection, and streaming support.

    Returns MakeResult with real token usage from litellm response.
    Both streaming and non-streaming paths capture usage.
    """
    settings = settings if settings is not None else _load_settings()
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
        # 串流路徑：收集 chunks；litellm stream_options 可帶回 usage（若模型支援）
        chunks: list[str] = []
        prompt_tokens = 0
        completion_tokens = 0
        try:
            stream = litellm.completion(
                stream=True,
                stream_options={"include_usage": True},
                messages=messages,
                max_tokens=max_tokens,
                **params,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content or "" if chunk.choices else ""
                if delta:
                    chunks.append(delta)
                    on_token(delta)
                # litellm 串流的最後一個 chunk 帶 usage（若模型支援）
                if hasattr(chunk, "usage") and chunk.usage:
                    prompt_tokens = getattr(chunk.usage, "prompt_tokens", 0) or 0
                    completion_tokens = getattr(chunk.usage, "completion_tokens", 0) or 0
            output = "".join(chunks)
            # 若串流未帶回 usage，以 0 填充（cost_known 仍為 True，讓 runner 知道是 litellm 路徑）
            return MakeResult.from_usage(output, prompt_tokens, completion_tokens)
        except Exception:
            if chunks:
                output = "".join(chunks)
                return MakeResult.from_usage(output, prompt_tokens, completion_tokens)
            raise

    # 非串流路徑：直接從 response.usage 取 token 數
    response = litellm.completion(messages=messages, max_tokens=max_tokens, **params)
    output = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0 if usage else 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0 if usage else 0
    return MakeResult.from_usage(output, prompt_tokens, completion_tokens)


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
