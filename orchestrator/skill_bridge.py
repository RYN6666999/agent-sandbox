"""Skill bridge — scan .claude/skills/, auto-register executable skills as executors."""
import json
import shlex
from pathlib import Path
from typing import Any

from orchestrator import executor_registry

# Where Claude CLI stores its skills
CLAUDE_SKILLS_DIR = Path.home() / ".claude" / "skills"

# Path to AgentOS settings (for persistence)
SETTINGS_PATH = Path(__file__).parent.parent / "data" / "settings.json"

# Executor types that should NOT be overwritten
_BUILTIN_NAMES = {"web-search", "agnes-analyze", "agnes-image", "agnes-video", "claude-code"}


def _load_settings() -> dict[str, Any]:
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except Exception:
        return {}


def _save_settings(data: dict[str, Any]) -> None:
    SETTINGS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _safe_executor_name(skill_name: str, suffix: str = "") -> str:
    """Build a unique executor name, avoid collisions with built-ins."""
    base = f"skill-{skill_name}"
    if suffix:
        base = f"{base}-{suffix}"
    if base in _BUILTIN_NAMES:
        base = f"claude-{base}"
    return base


def _read_skill_metadata(skill_dir: Path) -> dict[str, Any]:
    """Parse SKILL.md for name/description/triggers."""
    meta: dict[str, Any] = {"name": skill_dir.name, "description": "", "triggers": []}
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return meta

    text = skill_md.read_text("utf-8", errors="replace")
    # Extract YAML front matter name
    for line in text.splitlines():
        if line.startswith("name:"):
            meta["name"] = line.split(":", 1)[1].strip().strip('"').strip("'")
        if line.startswith("description:"):
            desc = line.split(":", 1)[1].strip().strip('"').strip("'")
            meta["description"] = desc[:200]  # cap length
        if "trigger" in line.lower() or "when" in line.lower():
            meta["triggers"].append(line.strip())
    return meta


def _register_executor(
    settings: dict[str, Any],
    name: str,
    defn: dict[str, Any],
) -> None:
    """Register in executor_registry and write to settings.json."""
    defn["name"] = name
    executor_registry.register(defn)
    settings.setdefault("executors", {})[name] = defn


def _resolve_script_path(rel_path: str) -> str:
    """Convert .claude/skills/ relative path to absolute for settings.json."""
    return str(CLAUDE_SKILLS_DIR.parent / rel_path)


# ── scanners ──────────────────────────────────────────────────────────────


def _scan_runpy_skill(
    settings: dict[str, Any],
    name: str,
    skill_dir: Path,
    meta: dict[str, Any],
) -> int:
    """Register skill with scripts/run.py — subcommands discovered from SKILL.md."""
    run_py = skill_dir / "scripts" / "run.py"
    if not run_py.exists():
        return 0

    # Check for subcommands mentioned in SKILL.md
    md_text = (skill_dir / "SKILL.md").read_text("utf-8", errors="replace")
    subcommands: list[str] = []

    # Pattern: `python scripts/run.py <subcommand>`
    for line in md_text.splitlines():
        if "run.py" in line and "--" not in line:
            parts = line.split()
            for i, p in enumerate(parts):
                if "run.py" in p and i + 1 < len(parts):
                    sub = parts[i + 1].replace("`", "").strip()
                    if sub and sub.endswith(".py") and sub not in subcommands:
                        subcommands.append(sub)

    # Always include the primary subcommands if mentioned in SKILL.md triggers
    known_primary = {"ask_question.py", "notebook_manager.py", "auth_manager.py"}
    for known in known_primary:
        if known not in subcommands and known in md_text:
            subcommands.append(known)

    if not subcommands:
        # Fallback: register the skill itself with no subcommand
        _register_executor(settings, _safe_executor_name(name), {
            "binary": "python", "flags": [str(run_py)],
            "type": "subprocess", "timeout": 120,
            "description": meta.get("description", f"Claude skill: {name}"),
        })
        return 1

    count = 0
    for sub in subcommands:
        sub_name = sub.replace(".py", "")
        executor_name = _safe_executor_name(name, sub_name)
        flags = [str(run_py), sub]

        # Subcommands that take a question as input
        needs_question = any(kw in sub_name.lower() for kw in ["ask", "question", "query"])
        prompt_flag = "--question" if needs_question else None
        add_args_after = "notebook" in sub_name.lower()  # e.g. notebook_manager needs URL arg

        _register_executor(settings, executor_name, {
            "binary": "python", "flags": flags,
            "prompt_flag": prompt_flag,
            "type": "subprocess", "timeout": 120,
            "description": f"{meta.get('description', name)} — {sub_name}",
        })
        count += 1
    return count


def _scan_scripts_dir(
    settings: dict[str, Any],
    name: str,
    skill_dir: Path,
    meta: dict[str, Any],
) -> int:
    """Register .py and .sh scripts in scripts/ (no run.py wrapper)."""
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.exists():
        return 0

    # Collect .py and .sh scripts (exclude __init__.py and non-script files)
    scripts: list[Path] = []
    for f in sorted(scripts_dir.iterdir()):
        if f.is_dir():
            continue  # skip subdirectories (e.g. design/cip)
        if f.suffix in (".py", ".sh") and f.name != "__init__.py":
            scripts.append(f)

    if not scripts:
        return 0

    count = 0
    for script in scripts:
        sub_name = script.stem
        executor_name = _safe_executor_name(name, sub_name)
        binary = "bash" if script.suffix == ".sh" else "python"
        _register_executor(settings, executor_name, {
            "binary": binary, "flags": [str(script)],
            "type": "subprocess", "timeout": 120,
            "description": f"{meta.get('description', name)} — {sub_name}",
        })
        count += 1
    return count


def _scan_sh_scripts(
    settings: dict[str, Any],
    name: str,
    skill_dir: Path,
    meta: dict[str, Any],
) -> int:
    """Register .sh scripts at skill root."""
    sh_scripts = sorted(skill_dir.glob("*.sh"))
    if not sh_scripts:
        return 0

    count = 0
    for script in sh_scripts:
        sub_name = script.stem
        executor_name = _safe_executor_name(name, sub_name)
        _register_executor(settings, executor_name, {
            "binary": "bash", "flags": [str(script)],
            "type": "subprocess", "timeout": 120,
            "description": f"{meta.get('description', name)} — {sub_name}",
        })
        count += 1
    return count


def _scan_py_root(
    settings: dict[str, Any],
    name: str,
    skill_dir: Path,
    meta: dict[str, Any],
) -> int:
    """Register .py files at skill root."""
    py_scripts = sorted(
        f for f in skill_dir.glob("*.py") if f.name != "__init__.py"
    )
    if not py_scripts:
        return 0

    count = 0
    for script in py_scripts:
        sub_name = script.stem
        executor_name = _safe_executor_name(name, sub_name)
        _register_executor(settings, executor_name, {
            "binary": "python", "flags": [str(script)],
            "type": "subprocess", "timeout": 120,
            "description": f"{meta.get('description', name)} — {sub_name}",
        })
        count += 1
    return count


# ── main ──────────────────────────────────────────────────────────────────


def scan(force: bool = False) -> dict[str, Any]:
    """Scan .claude/skills/ and register executable skills as executors.

    Args:
        force: If True, re-scan and overwrite existing skill executors.

    Returns:
        dict with keys: registered (int), skipped (int), skills (list[str]).
    """
    settings = _load_settings()
    existing = set(settings.get("executors", {}).keys())

    # When force=True, remove all previous skill-* executors first
    if force:
        executors = settings.get("executors", {})
        for key in list(executors.keys()):
            if key.startswith("skill-"):
                del executors[key]
        # Also clear from in-memory registry
        for key in list(executor_registry._registry.keys()):
            if key.startswith("skill-"):
                executor_registry._registry.pop(key, None)
        existing = set(executors.keys())

    registered = 0
    skipped = 0
    skill_names: list[str] = []

    if not CLAUDE_SKILLS_DIR.exists():
        return {"registered": 0, "skipped": 0, "skills": [], "error": f"{CLAUDE_SKILLS_DIR} not found"}

    for skill_dir in sorted(CLAUDE_SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue

        name = skill_dir.name
        meta = _read_skill_metadata(skill_dir)

        # Skip if already registered (unless force)
        if not force:
            marker = f"skill-{name}"
            if any(e.startswith(marker) for e in existing):
                skipped += 1
                continue

        count = 0
        # Priority: skills with run.py → skip scripts/ scan (run.py handles venv + dispatch)
        has_runpy = (skill_dir / "scripts" / "run.py").exists()

        count += _scan_runpy_skill(settings, name, skill_dir, meta)
        if not has_runpy:
            count += _scan_scripts_dir(settings, name, skill_dir, meta)
        count += _scan_sh_scripts(settings, name, skill_dir, meta)
        count += _scan_py_root(settings, name, skill_dir, meta)

        if count > 0:
            registered += count
            skill_names.append(name)
        else:
            skipped += 1

    # Persist
    _save_settings(settings)
    return {"registered": registered, "skipped": skipped, "skills": skill_names}


def scan_and_report() -> None:
    """Scan and print a summary."""
    result = scan(force=False)
    print(f"Registered: {result['registered']} executors from {len(result['skills'])} skills")
    print(f"Skipped (no scripts / already registered): {result['skipped']}")
    if result["skills"]:
        print(f"Skills: {', '.join(result['skills'])}")


if __name__ == "__main__":
    scan_and_report()