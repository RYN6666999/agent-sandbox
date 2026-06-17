"""Stage-1: rule-based classifier. Free, covers ~70% of obvious cases."""
from dataclasses import dataclass
from enum import Enum


class TaskType(str, Enum):
    ARCHITECTURE  = "architecture"
    FEATURE       = "feature"
    TEST          = "test"
    HIGH_FREQ     = "high_freq"
    SUMMARY       = "summary"
    SENSITIVE     = "sensitive"
    DANGER        = "danger"


@dataclass
class RuleHit:
    task_type: TaskType
    confidence: float
    matched_keyword: str


# Keywords → TaskType. First match wins, so order matters (more specific first).
_RULES: list[tuple[set[str], TaskType]] = [
    # Sensitive (highest priority — must check before anything else)
    ({"secret", "password", "token", "credential", "私密", "機密", "敏感", "private", "sensitive"}, TaskType.SENSITIVE),
    # Danger / irreversible
    ({"delete", "drop", "rm -rf", "format", "destroy", "truncate", "不可逆", "危險", "irreversible", "danger"}, TaskType.DANGER),
    # Architecture / complex reasoning
    ({"architect", "design", "system design", "架構", "設計", "plan", "strategy", "trade-off", "tradeoff"}, TaskType.ARCHITECTURE),
    # Summary / long-doc
    ({"summarize", "summary", "摘要", "長文", "digest", "tldr", "tl;dr"}, TaskType.SUMMARY),
    # Test writing
    ({"test", "測試", "unit test", "pytest", "spec", "assert", "tdd"}, TaskType.TEST),
    # High-frequency simple tasks
    ({"rename", "format", "lint", "格式", "重命名", "fix typo", "typo", "高頻", "雜活", "simple", "quick"}, TaskType.HIGH_FREQ),
    # Feature implementation (broad catch — keep last)
    ({"implement", "build", "write", "create", "add", "實作", "開發", "新增", "function", "api", "endpoint"}, TaskType.FEATURE),
]


def rule_match(task: str) -> RuleHit | None:
    lower = task.lower()
    for keywords, task_type in _RULES:
        for kw in keywords:
            if kw in lower:
                return RuleHit(task_type=task_type, confidence=0.85, matched_keyword=kw)
    return None
