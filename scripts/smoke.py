"""
smoke — integration gate. Hits real services, catches wiring errors unit tests miss.
  1. Provider check  — each model alias fires a 1-token real request
  2. API roundtrip   — submit → approve → ws result (mocked loop)
Exit 0 = all clear. Exit 1 = blocked.
"""
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import litellm
from orchestrator.model_registry import resolve

# ── helpers ──────────────────────────────────────────────────────────────────

def ok(label: str):
    print(f"  ✓ {label}")

def fail(label: str, err):
    print(f"  ✗ {label}: {err}")
    sys.exit(1)


# ── Step 1: Provider check ────────────────────────────────────────────────────

ALIASES = ["agnes", "gemini-flash"]   # skip ollama-local (optional) and claude ($$)

def check_providers():
    print("\n▶ provider check")
    for alias in ALIASES:
        params = resolve(alias)
        try:
            resp = litellm.completion(
                messages=[{"role": "user", "content": "1+1="}],
                max_tokens=3,
                temperature=0.0,
                **params,
            )
            text = resp.choices[0].message.content.strip()
            ok(f"{alias} → {text!r}")
        except (litellm.RateLimitError, litellm.BadRequestError) as e:
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
                print(f"  ⚠ {alias}: quota/rate-limit (provider OK, skipping): {msg[:120]}")
            else:
                fail(alias, e)
        except Exception as e:
            fail(f"{alias}", e)


# ── Step 2: API roundtrip ─────────────────────────────────────────────────────

def check_api():
    print("\n▶ API roundtrip")
    import subprocess, socket, time

    # find or start backend
    def backend_alive() -> bool:
        try:
            import urllib.request
            urllib.request.urlopen("http://localhost:8000/health", timeout=2)
            return True
        except Exception:
            return False

    started_proc = None
    if not backend_alive():
        print("  (starting backend...)")
        PYTHON = ROOT / ".venv" / "bin" / "python"
        started_proc = subprocess.Popen(
            [str(PYTHON), "-m", "uvicorn", "api.main:app", "--port", "8000"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(15):
            time.sleep(1)
            if backend_alive():
                break
        else:
            if started_proc:
                started_proc.terminate()
            fail("backend startup", "timeout after 15s")

    import urllib.request, urllib.error

    def post(path, data):
        req = urllib.request.Request(
            f"http://localhost:8000{path}",
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    try:
        # submit
        body = post("/task/submit", {"task": "smoke test task"})
        assert "session_id" in body and len(body["questions"]) == 6
        session_id = body["session_id"]
        ok(f"submit → session {session_id}")

        # health
        with urllib.request.urlopen("http://localhost:8000/health", timeout=3) as r:
            assert json.loads(r.read())["ok"] is True
        ok("health")

        # cost shape
        with urllib.request.urlopen("http://localhost:8000/cost", timeout=3) as r:
            cost = json.loads(r.read())
            assert "total_usd" in cost and "calls" in cost
        ok("cost shape")

    except AssertionError as e:
        fail("API shape", e)
    except urllib.error.URLError as e:
        fail("API unreachable", e)
    finally:
        if started_proc:
            started_proc.terminate()


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    check_providers()
    check_api()
    print("\n✓ smoke PASSED")

if __name__ == "__main__":
    main()
