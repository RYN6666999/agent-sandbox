"""
Skill injection adapter.
Claude family: skills loaded natively (pass skill names).
Others (Gemini, Agnes, Ollama, etc.): skills downgraded to plain text in system prompt.
"""
CLAUDE_MODELS = {"claude-sonnet", "claude-opus", "claude-haiku", "claude"}

# Minimal skill text for non-Claude models.
# Full skill files live in ~/.claude/skills/ — these are stripped-down summaries.
SKILL_PROMPTS: dict[str, str] = {
    "ponytail": (
        "You are a lazy senior developer. Stop at the first rung that works: "
        "stdlib > native platform > installed dep > one line > minimum code. "
        "No unrequested abstractions. Shortest working diff wins. "
        "Code first, then at most 3 short lines on what was skipped and when to add it."
    ),
    "caveman": (
        "Respond terse like smart caveman. Drop articles, filler, pleasantries. "
        "Fragments OK. Technical terms exact. Code unchanged. "
        "Pattern: [thing] [action] [reason]. [next step]."
    ),
    "align": (
        "Before starting any task, ask: Why? Give me input→output example? "
        "What would feel wrong? What are the red lines? "
        "Restate answers and get explicit confirmation before proceeding."
    ),
}


def build_system_prompt(skills: list[str], model: str, base_prompt: str = "") -> str:
    """
    For Claude: return base_prompt only (skills injected natively by caller).
    For others: append skill text to base_prompt.
    """
    is_claude = any(m in model.lower() for m in CLAUDE_MODELS)
    if is_claude:
        return base_prompt

    injected = []
    for skill in skills:
        text = SKILL_PROMPTS.get(skill)
        if text:
            injected.append(f"[{skill.upper()} SKILL]\n{text}")

    if not injected:
        return base_prompt

    skill_block = "\n\n".join(injected)
    return f"{base_prompt}\n\n{skill_block}".strip()
