"""
guard:all — full project gate. Runs in order, exits on first failure.
  1. guard:contracts  (Pydantic contract tests)
  2. pytest all       (unit + API tests)
  3. tsc --noEmit     (TypeScript types)
Exit 0 = all clear. Exit 1 = blocked.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PYTHON = ROOT / ".venv" / "bin" / "python"
UI = ROOT / "ui"


def run(label: str, cmd: list[str], cwd: Path = ROOT) -> bool:
    print(f"\n▶ {label}")
    r = subprocess.run(cmd, cwd=cwd)
    ok = r.returncode == 0
    print("✓" if ok else "✗", label)
    return ok


def main():
    steps = [
        ("guard:contracts", [str(PYTHON), "scripts/guard_contracts.py"]),
        ("pytest all",      [str(PYTHON), "-m", "pytest", "tests/", "-q"]),
        ("smoke",           [str(PYTHON), "scripts/smoke.py"]),
        ("tsc --noEmit",    ["npx", "tsc", "--noEmit"]),
    ]

    for label, cmd in steps:
        cwd = UI if label.startswith("tsc") else ROOT
        if not run(label, cmd, cwd):
            print(f"\n✗ guard:all FAILED at [{label}]")
            sys.exit(1)

    print("\n✓ guard:all PASSED")


if __name__ == "__main__":
    main()
