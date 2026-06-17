"""
guard:contracts — runs test_contracts.py as the authoritative contract check.
Exit 0 = all contracts valid. Exit 1 = any failure.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PYTHON = ROOT / ".venv" / "bin" / "python"


def main():
    result = subprocess.run(
        [str(PYTHON), "-m", "pytest", "tests/test_contracts.py", "-v", "--tb=short"],
        cwd=ROOT,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
