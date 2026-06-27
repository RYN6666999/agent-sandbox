"""Stage-2: LLM classifier for the ~30% rule misses.

Model is read from data/settings.json["classifier_model"] so it can be swapped
without touching code. Defaults to "openrouter-classifier" (openai/gpt-oss-120b
via OpenRouter) which has calibrated confidence scores for D11 routing gate.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import litellm
from router.rules import TaskType
from orchestrator.model_registry import resolve as _resolve

_SETTINGS_PATH = Path(__file__).parent.parent / "data" / "settings.json"
_DEFAULT_CLASSIFIER = "openrouter-classifier"


def _classifier_model() -> str:
    try:
        return json.loads(_SETTINGS_PATH.read_text()).get("plan_model", _DEFAULT_CLASSIFIER)
    except Exception:
        return _DEFAULT_CLASSIFIER


# ── 7-category classification (model/skill routing) ────────────────────────

PROMPT = """\
Classify the following task into exactly one category.

Categories:
- architecture: system design, planning, complex reasoning, trade-offs
- feature: implement code, build functions, write APIs
- test: write tests, TDD, assertions, test coverage
- high_freq: rename, format, lint, typos, simple edits
- summary: summarize documents, digest long text, tldr
- sensitive: involves passwords, tokens, private data, credentials
- danger: delete, drop, irreversible, destructive operations

Respond with JSON only: {"type": "<category>", "confidence": <0.0-1.0>}

Task: {task}
"""

# System prompt for routing intent (D11): 3-way classification
# Requires response_format=json_object; works best with reasoning models.
_ROUTING_SYSTEM = (
    "You classify user task routing. Always respond with valid JSON containing exactly "
    "two keys: \"category\" (one of: answer/code/unclear) and \"reason\" (one sentence).\n\n"
    "\"answer\" = clearly only needs a direct reply or explanation. "
    "This includes short commands in any language (e.g. \"系統存活檢查\", \"check status\", "
    "\"說你好世界\", \"Python 版本\" — these are direct requests, not ambiguous).\n"
    "\"code\" = clearly needs working code or runnable artifact (e.g. \"寫一個函式 add(a,b)\", "
    "\"implement binary search\").\n"
    "\"unclear\" = could plausibly need either — the intent is genuinely ambiguous "
    "(e.g. \"幫我優化\", \"改一下顏色\").\n\n"
    "Examples:\n"
    "  \"系統存活檢查\" → {\"category\": \"answer\", \"reason\": \"direct request to check system status\"}\n"
    "  \"說你好世界\" → {\"category\": \"answer\", \"reason\": \"direct greeting request\"}\n"
    "  \"Python 版本是多少\" → {\"category\": \"answer\", \"reason\": \"direct question about version\"}\n"
    "  \"寫一個函式 add(a,b) 回傳兩數相加\" → {\"category\": \"code\", \"reason\": \"needs code implementation\"}\n"
    "  \"幫我優化\" → {\"category\": \"unclear\", \"reason\": \"no target specified — genuinely ambiguous\"}\n"
    "  \"改一下顏色\" → {\"category\": \"unclear\", \"reason\": \"no target specified — genuinely ambiguous\"}"
)


@dataclass
class ClassifyResult:
    task_type: TaskType
    confidence: float
    source: str                 # 'llm' | 'fallback'
    classifier_model: str | None
    fallback_reason: str | None = None
    retry_count: int = 0


@dataclass
class RoutingIntent:
    category: str               # 'answer' | 'code' | 'unclear'
    reason: str
    source: str                 # 'llm' | 'fallback'
    classifier_model: str | None


def routing_intent(task: str) -> RoutingIntent:
    """3-way routing intent: answer / code / unclear.

    Uses response_format=json_object so the model cannot return freeform text.
    'unclear' → D11: trigger clarify_routing, ask user A/B question.
    """
    model_alias = _classifier_model()
    try:
        params = _resolve(model_alias)
        resp = litellm.completion(
            messages=[
                {"role": "system", "content": _ROUTING_SYSTEM},
                {"role": "user", "content": task},
            ],
            max_tokens=200,   # JSON output only needs ~50 tokens; CoT is internal
            temperature=0.0,
            response_format={"type": "json_object"},
            **params,
        )
        raw = resp.choices[0].message.content or ""
        data = json.loads(raw)
        cat = data.get("category", "unclear")
        if cat not in ("answer", "code", "unclear"):
            cat = "unclear"
        return RoutingIntent(
            category=cat,
            reason=data.get("reason", ""),
            source="llm",
            classifier_model=model_alias,
        )
    except Exception as exc:
        # On any failure treat as unclear → safer to ask than to guess
        return RoutingIntent(
            category="unclear",
            reason=f"classifier error: {exc}",
            source="fallback",
            classifier_model=model_alias,
        )


def llm_classify_detailed(task: str) -> ClassifyResult:
    """Returns full classifier trace (7-category). Falls back to FEATURE on any error."""
    model_alias = _classifier_model()
    try:
        params = _resolve(model_alias)
        resp = litellm.completion(
            messages=[{"role": "user", "content": PROMPT.format(task=task)}],
            max_tokens=2000,
            temperature=0.0,
            **params,
        )
        raw = (resp.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        import re
        m = re.search(r'\{[^}]+\}', raw)
        raw = m.group(0) if m else raw
        data = json.loads(raw)
        task_type = TaskType(data["type"])
        confidence = float(data.get("confidence", 0.6))
        return ClassifyResult(
            task_type=task_type,
            confidence=confidence,
            source="llm",
            classifier_model=model_alias,
            retry_count=0,
        )
    except Exception as exc:
        return ClassifyResult(
            task_type=TaskType.FEATURE,
            confidence=0.3,
            source="fallback",
            classifier_model=model_alias,
            fallback_reason=str(exc),
            retry_count=0,
        )


def llm_classify(task: str) -> tuple[TaskType, float]:
    """Backwards-compatible wrapper returning only (TaskType, confidence)."""
    result = llm_classify_detailed(task)
    return result.task_type, result.confidence
