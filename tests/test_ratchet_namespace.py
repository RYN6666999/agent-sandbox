"""Ratchet namespace isolation tests.

Runs checks in subprocesses so module-level globals never leak into other tests.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def _run_probe(tmp_path: Path, namespace: str | None):
    env = os.environ.copy()
    env["AGENTOS_RATCHET_DATA_DIR"] = str(tmp_path)
    if namespace is None:
        env.pop("AGENTOS_RATCHET_NAMESPACE", None)
    else:
        env["AGENTOS_RATCHET_NAMESPACE"] = namespace

    cmd = [
        sys.executable,
        "-c",
        "from router.ratchet import _RATCHET_NAMESPACE,_RATCHET_PATH,_EVENTS_PATH;"
        "import json;"
        "print(json.dumps({'ns':_RATCHET_NAMESPACE,'ratchet':str(_RATCHET_PATH),'events':str(_EVENTS_PATH)}))",
    ]
    result = subprocess.run(
        cmd,
        cwd=Path(__file__).parent.parent,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip())


def _run_save(tmp_path: Path, namespace: str | None):
    env = os.environ.copy()
    env["AGENTOS_RATCHET_DATA_DIR"] = str(tmp_path)
    if namespace is None:
        env.pop("AGENTOS_RATCHET_NAMESPACE", None)
    else:
        env["AGENTOS_RATCHET_NAMESPACE"] = namespace

    cmd = [
        sys.executable,
        "-c",
        "from router.ratchet import RatchetEntry, save_ratchet;"
        "save_ratchet({'file_write': RatchetEntry(task_class='file_write', verified_count=1)})",
    ]
    subprocess.run(
        cmd,
        cwd=Path(__file__).parent.parent,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


def test_default_namespace_uses_prod_filenames(tmp_path):
    data = _run_probe(tmp_path, None)
    assert data["ns"] == "prod"
    assert Path(data["ratchet"]).name == "ratchet.json"
    assert Path(data["events"]).name == "ratchet_events.log"


def test_nonprod_namespace_uses_isolated_filenames(tmp_path):
    data = _run_probe(tmp_path, "test")
    assert data["ns"] == "test"
    assert Path(data["ratchet"]).name == "ratchet.test.json"
    assert Path(data["events"]).name == "ratchet_events.test.log"


def test_nonprod_namespace_does_not_touch_prod_file(tmp_path):
    _run_save(tmp_path, "ci")
    assert (tmp_path / "ratchet.ci.json").exists()
    assert not (tmp_path / "ratchet.json").exists()


def test_invalid_namespace_falls_back_to_prod(tmp_path):
    data = _run_probe(tmp_path, "../bad/ns")
    assert data["ns"] == "prod"
    assert Path(data["ratchet"]).name == "ratchet.json"
