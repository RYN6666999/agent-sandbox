"""Stage-2: cheap LLM classifier for the ~30% rule misses."""
import json
import os
import sys
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


def llm_classify(task: str) -> tuple[TaskType, float]:
    """Returns (TaskType, confidence). Falls back to FEATURE on any error."""
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
        return task_type, confidence
    except Exception:
        return TaskType.FEATURE, 0.3   # safe default
