"""Stage-2: cheap LLM classifier for the ~30% rule misses."""
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

CLASSIFIER_MODEL = "agnes"  # free, fast, good enough for classification

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


@dataclass
class ClassifyResult:
    task_type: TaskType
    confidence: float
    source: str                 # 'llm' | 'fallback'
    classifier_model: str | None
    fallback_reason: str | None = None
    retry_count: int = 0


def llm_classify_detailed(task: str) -> ClassifyResult:
    """Returns full classifier trace. Falls back to FEATURE on any error."""
    try:
        params = _resolve(CLASSIFIER_MODEL)
        resp = litellm.completion(
            messages=[{"role": "user", "content": PROMPT.format(task=task)}],
            max_tokens=50,
            temperature=0.0,
            **params,
        )
        raw = resp.choices[0].message.content.strip()
        # strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        task_type = TaskType(data["type"])
        confidence = float(data.get("confidence", 0.6))
        return ClassifyResult(
            task_type=task_type,
            confidence=confidence,
            source="llm",
            classifier_model=CLASSIFIER_MODEL,
            retry_count=0,
        )
    except Exception as exc:
        return ClassifyResult(
            task_type=TaskType.FEATURE,
            confidence=0.3,
            source="fallback",
            classifier_model=CLASSIFIER_MODEL,
            fallback_reason=str(exc),
            retry_count=0,
        )


def llm_classify(task: str) -> tuple[TaskType, float]:
    """Backwards-compatible wrapper returning only (TaskType, confidence)."""
    result = llm_classify_detailed(task)
    return result.task_type, result.confidence
