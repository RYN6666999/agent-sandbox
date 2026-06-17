"""align-before-build CLI: interactive gate → TaskSpec → .sdd/"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from align.core import parse_answers_to_spec, ALIGN_QUESTIONS

SDD_DIR = Path(__file__).parent.parent / ".sdd"
SDD_DIR.mkdir(exist_ok=True)

QUESTIONS = [(q["key"], q["q"]) for q in ALIGN_QUESTIONS[:4]]

STOP_QUESTIONS = [
    ("stop_metric", "達標條件是什麼？用什麼客觀標準判斷「做完了」？"),
    ("max_rounds",  "最多跑幾輪 Maker/Checker 迭代？(預設 5)"),
]


def ask(prompt: str) -> str:
    print(f"\n▶ {prompt}")
    return input("  你: ").strip()


def parse_list(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def parse_io(s: str) -> dict:
    """Accept 'input=x, output=y' or just free text."""
    parts = s.split("→") if "→" in s else s.split("->")
    if len(parts) == 2:
        return {"input": parts[0].strip(), "expected_output": parts[1].strip()}
    return {"input": s, "expected_output": ask("  預期輸出是什麼？")}


def run_align() -> TaskSpec:
    print("\n=== align-before-build ===")
    print("開工前先對齊。四個問題，回答完我複述確認。\n")

    answers = {}
    for key, q in QUESTIONS:
        answers[key] = ask(q)

    # stop conditions
    stop_metric = ask(STOP_QUESTIONS[0][1])
    max_rounds_str = ask(STOP_QUESTIONS[1][1])
    max_rounds = int(max_rounds_str) if max_rounds_str.isdigit() else 5

    io = parse_io(answers["io"])
    taste = parse_list(answers["taste"])
    boundaries = parse_list(answers["boundary"])

    print("\n--- 複述確認 ---")
    print(f"目的  : {answers['why']}")
    print(f"輸入  : {io.get('input')}")
    print(f"輸出  : {io.get('expected_output')}")
    print(f"味道  : {taste}")
    print(f"紅線  : {boundaries}")
    print(f"達標  : {stop_metric}")
    print(f"最多輪: {max_rounds}")

    confirm = input("\n這樣對嗎？(y/n/修): ").strip().lower()
    if confirm != "y":
        print("重新來一遍。")
        return run_align()

    answers["stop_metric"] = stop_metric
    answers["max_rounds"] = str(max_rounds)
    spec = parse_answers_to_spec(answers)

    # persist to .sdd/
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    out = SDD_DIR / f"task_spec_{ts}.json"
    out.write_text(spec.model_dump_json(indent=2))
    print(f"\n✓ TaskSpec saved → {out}")
    return spec


if __name__ == "__main__":
    spec = run_align()
    print("\n=== TaskSpec ===")
    print(spec.model_dump_json(indent=2))
