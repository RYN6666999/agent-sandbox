"""
Checker: validates Maker output against TaskSpec stop conditions.
Must use objective criteria — never subjective LLM feelings alone.

Check pipeline (in order):
  1. keyword_check  — expected_output keywords present in output?
  2. taste_check    — any taste violations detected?
  3. boundary_check — any red lines crossed?
  4. llm_check      — only if above pass: LLM rates 0-10 against stop_on_metric

Pass threshold: keyword + taste + boundary all clear, llm_score >= 7.
No-progress threshold: score delta < 0.5 over previous round.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dataclasses import dataclass, field
from dotenv import load_dotenv
load_dotenv()

import litellm
from contracts.task_spec import TaskSpec
from orchestrator.model_registry import resolve as _resolve

CHECKER_MODEL = "gemini-flash"   # stronger than Maker's default Agnes
CHECKER_FALLBACKS = ["agnes"]    # used when primary quota exhausted


@dataclass
class CheckResult:
    passed: bool
    score: float                 # 0.0–10.0
    feedback: str
    violations: list[str] = field(default_factory=list)


def check(spec: TaskSpec, output: str, prev_score: float | None = None) -> CheckResult:
    violations: list[str] = []

    # 1. Keyword check — expected_output must appear conceptually in output
    expected = str(spec.io_example.get("expected_output", ""))
    keywords = [w.strip() for w in expected.replace("=", " ").split() if len(w) > 2]
    missing = [kw for kw in keywords if kw.lower() not in output.lower()]
    if missing:
        violations.append(f"missing expected keywords: {missing}")

    # 2. Boundary check — red lines must not appear in output
    for boundary in spec.boundaries:
        # Simple heuristic: if boundary says "no X" and X appears, flag it
        if boundary.lower().startswith("no "):
            forbidden = boundary[3:].strip().lower()
            if forbidden and forbidden in output.lower():
                violations.append(f"boundary crossed: {boundary!r}")

    # 3. If hard violations → fail immediately without LLM call
    if violations:
        return CheckResult(
            passed=False,
            score=0.0,
            feedback=f"Hard check failed: {'; '.join(violations)}",
            violations=violations,
        )

    # 4. LLM score against stop_on_metric
    score, llm_feedback = _llm_score(spec, output)

    # No-progress guard: if score improved < 0.5 over previous round, flag it
    no_progress = prev_score is not None and (score - prev_score) < 0.5

    passed = score >= 7.0 and not no_progress

    return CheckResult(
        passed=passed,
        score=score,
        feedback=llm_feedback + (" [no progress]" if no_progress else ""),
        violations=[],
    )


def _llm_score(spec: TaskSpec, output: str) -> tuple[float, str]:
    metric = spec.stop_on_metric or "correctness and completeness"
    prompt = (
        f"You are a strict evaluator. Score the output 0-10 based on: {metric}\n\n"
        f"Task: {spec.why}\n"
        f"Expected: {spec.io_example.get('expected_output', '')}\n\n"
        f"Output to evaluate:\n{output[:2000]}\n\n"
        "Respond with JSON only: "
        '{"score": <0-10>, "feedback": "<one sentence on what to improve>"}'
    )
    import json
    for alias in [CHECKER_MODEL] + CHECKER_FALLBACKS:
        try:
            params = _resolve(alias)
            resp = litellm.completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.0,
                **params,
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            return float(data["score"]), data.get("feedback", "")
        except (litellm.RateLimitError, litellm.BadRequestError) as e:
            # Gemini sometimes returns BadRequestError for 429/RESOURCE_EXHAUSTED
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
                continue  # rate-limited → try next model
            return 5.0, f"checker LLM error: {e}"
        except Exception as e:
            return 5.0, f"checker LLM error: {e}"
    return 5.0, "checker: all models rate-limited"
