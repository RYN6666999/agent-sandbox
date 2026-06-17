"""Shared align logic. Used by both CLI (align.py) and API (api/main.py)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from contracts.task_spec import TaskSpec


def synthesize_task_brief(answers: dict) -> str:
    """
    Combine align Q&A into one clear, executable task description.
    Pure rules, 0 LLM calls. Missing fields are omitted (no empty placeholders).
    """
    parts: list[str] = []

    why = (answers.get("why") or "").strip()
    if why:
        parts.append(why)

    io_raw = (answers.get("io") or "").strip()
    if io_raw:
        parts.append(f"具體要做：{io_raw}")

    stop = (answers.get("stop_metric") or "").strip()
    if stop:
        parts.append(f"完成判準：{stop}")

    boundary = (answers.get("boundary") or "").strip()
    if boundary:
        parts.append(f"限制：{boundary}")

    taste = (answers.get("taste") or "").strip()
    if taste:
        parts.append(f"品味要求：{taste}")

    return " — ".join(parts) if parts else "未填寫任務描述"


def parse_answers_to_spec(answers: dict) -> TaskSpec:
    """Convert raw align answers dict → validated TaskSpec."""
    io_raw = answers.get("io", "")
    parts = io_raw.split("→") if "→" in io_raw else io_raw.split("->")
    io_example = (
        {"input": parts[0].strip(), "expected_output": parts[1].strip()}
        if len(parts) == 2
        else {"input": io_raw, "expected_output": io_raw}
    )

    def split_list(s: str) -> list[str]:
        return [x.strip() for x in s.split(",") if x.strip()]

    max_rounds_raw = answers.get("max_rounds", "5")
    max_rounds = int(max_rounds_raw) if str(max_rounds_raw).isdigit() else 5

    return TaskSpec(
        why=answers.get("why", ""),
        io_example=io_example,
        taste=split_list(answers.get("taste", "")),
        boundaries=split_list(answers.get("boundary", "")),
        stop_on_metric=answers.get("stop_metric", "correctness"),
        max_rounds=max_rounds,
    )


ALIGN_QUESTIONS = [
    {"key": "why",         "q": "為什麼要做這件事？目的是什麼？"},
    {"key": "io",          "q": "給一個具體例子：輸入 → 預期輸出"},
    {"key": "taste",       "q": "什麼跑掉就不對味？(逗號分隔)"},
    {"key": "boundary",    "q": "紅線在哪？何時應該停？(逗號分隔)"},
    {"key": "stop_metric", "q": "達標條件是什麼？用什麼客觀標準判斷完成？"},
    {"key": "max_rounds",  "q": "最多跑幾輪？(預設 5)"},
]
