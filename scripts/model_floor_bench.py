#!/usr/bin/env python3
"""Model-floor benchmark — find the lowest usable model for the maker role.

Runs each model through a scaffolded harness (output contract + format example +
1-line-CoT + TRANSLATED pytest feedback) against a small coding suite. Oracle =
real pytest (checker.run_pytest). A model is "usable" if it clears the suite.

Costs money (real OpenRouter calls). Opt-in:
    OPENROUTER_API_KEY=... python scripts/model_floor_bench.py
    python scripts/model_floor_bench.py --bare   # A/B: no scaffold, raw feedback

Results snapshot lives in docs/benchmarks/model-floor.md. Re-run when adding a
model or changing the scaffold; paste the new table there.
"""
import sys, os, re, time, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import litellm
from orchestrator.checker import run_pytest
litellm.suppress_debug_info = True

# dumbest -> most capable (edit freely)
MODELS = [
    ("llama-3.2-1b", "openrouter/meta-llama/llama-3.2-1b-instruct"),
    ("llama-3.2-3b", "openrouter/meta-llama/llama-3.2-3b-instruct"),
    ("gemma-3-4b",   "openrouter/google/gemma-3-4b-it"),
    ("qwen-2.5-7b",  "openrouter/qwen/qwen-2.5-7b-instruct"),
    ("llama-3.1-8b", "openrouter/meta-llama/llama-3.1-8b-instruct"),
    ("gemma-3-12b",  "openrouter/google/gemma-3-12b-it"),
    ("deepseek",     "openrouter/deepseek/deepseek-chat"),
    ("gpt-4o-mini",  "openrouter/openai/gpt-4o-mini"),
]

TASKS = [
    ("two_sum", "two_sum(nums,target): return indices [i,j] (i<j) summing to target.",
     "from solution import two_sum\ndef test_it():\n assert two_sum([2,7,11,15],9)==[0,1]\n assert two_sum([3,2,4],6)==[1,2]\n assert two_sum([3,3],6)==[0,1]\n"),
    ("roman_to_int", "roman_to_int(s): Roman numeral -> int (subtractive IV/IX/XL/XC/CD/CM).",
     "from solution import roman_to_int\ndef test_it():\n assert roman_to_int('III')==3\n assert roman_to_int('IV')==4\n assert roman_to_int('IX')==9\n assert roman_to_int('LVIII')==58\n assert roman_to_int('MCMXCIV')==1994\n"),
    ("valid_parens", "valid_parens(s): True iff ()[]{} balanced and correctly nested.",
     "from solution import valid_parens\ndef test_it():\n assert valid_parens('()[]{}')\n assert not valid_parens('(]')\n assert valid_parens('([{}])')\n assert not valid_parens('([)]')\n assert valid_parens('')\n assert not valid_parens('(')\n"),
    ("group_anagrams", "group_anagrams(words): group anagrams; list of groups, each sorted, groups sorted by first word.",
     "from solution import group_anagrams\ndef test_it():\n r=group_anagrams(['eat','tea','tan','ate','nat','bat'])\n assert sorted([sorted(g) for g in r])==sorted([['ate','eat','tea'],['nat','tan'],['bat']])\n assert group_anagrams([])==[]\n"),
]

SCAF_SYS = ("You are a careful Python coder. Output exactly ONE ```python block = the "
            "COMPLETE solution.py; no prose outside it; begin with a '# algo: ...' comment.")
BARE_SYS = "You are a Python coder. Output the full solution.py."
EX = "\n\nFormat:\n```python\n# algo: one-line plan\ndef f(x):\n    return x\n```"


def extract(raw):
    m = re.search(r"```(?:python|py)?\s*\n(.*?)(?:```|\Z)", raw, re.DOTALL)
    return (m.group(1) if m else raw).strip()

def complete(c):
    return "def " in c and c.count("(") == c.count(")") and len(c) > 30

def translate(stdout):
    s = stdout or ""
    if any(k in s for k in ("Interrupted", "collection", "SyntaxError", "ImportError", "IndentationError", "NameError")):
        return "Your code did NOT import/parse. Output the COMPLETE solution.py in ONE ```python block."
    al = next((l.strip() for l in s.splitlines() if l.strip().startswith("assert ")), "")
    el = next((l.strip() for l in s.splitlines() if l.strip().startswith("E ")), "")
    return f"A test failed:\n {al}\n {el}\nFix the logic. Output ONLY the full corrected ```python block."

def gen(model, msgs, key, tries=3):
    raw = ""
    for _ in range(tries):
        try:
            r = litellm.completion(messages=msgs, max_tokens=1200, temperature=0.2,
                                   timeout=60, model=model, api_key=key)
            raw = r.choices[0].message.content or ""
            if complete(extract(raw)):
                return raw, extract(raw)
        except Exception:
            time.sleep(1)
    return raw, extract(raw)

def solve(model, problem, oracle, key, scaffold, rounds=4):
    sysmsg = SCAF_SYS if scaffold else BARE_SYS
    u = problem + (EX if scaffold else "") + "\n\nMust pass:\n```python\n" + oracle + "\n```"
    msgs = [{"role": "system", "content": sysmsg}, {"role": "user", "content": u}]
    for rnd in range(1, rounds + 1):
        raw, code = gen(model, msgs, key)
        if not complete(code):
            if rnd == rounds:
                return False
            msgs += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": "Output the COMPLETE solution.py in ONE python block."}]
            continue
        pr = run_pytest(code, oracle)
        if pr.passed:
            return True
        fb = translate(pr.stdout) if scaffold else ("pytest FAILED:\n" + (pr.stdout or "")[:700])
        msgs += [{"role": "assistant", "content": raw}, {"role": "user", "content": fb}]
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bare", action="store_true", help="no scaffold (A/B baseline)")
    args = ap.parse_args()
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("set OPENROUTER_API_KEY")
    scaffold = not args.bare
    N = len(TASKS)
    print(f"mode: {'BARE' if args.bare else 'SCAFFOLDED'}   suite: {N} tasks\n")
    print(f"{'model':14} {'pass':6} fails")
    for name, model in MODELS:
        res = [(t, solve(model, p, o, key, scaffold)) for t, p, o in TASKS]
        p = sum(ok for _, ok in res)
        fails = " ".join(t for t, ok in res if not ok) or "-"
        print(f"{name:14} {p}/{N:<4} {fails}")


if __name__ == "__main__":
    main()
