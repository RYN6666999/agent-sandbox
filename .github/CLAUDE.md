# AgentOS — CLAUDE.md

> Companion to AGENTS.md. Tech spec, architecture, and development rules for AI agents.

## Tech Stack

- **Language**: Python 3.11+
- **Framework**: FastAPI (api/main.py)
- **Package manager**: uv (astral-sh)
- **Database**: SQLite via aiosqlite
- **Testing**: pytest + pydantic-contracts
- **CI**: GitHub Actions (test.yml)
- **Deployment**: macOS LaunchAgent (install-autostart.sh)

## Architecture

```
agent-sandbox/
├── api/                     # FastAPI endpoints
│   ├── main.py              # App entry, CORS, router mount
│   ├── routes/              # Route handlers
│   │   ├── task.py          # /task/make, /task/verify
│   │   ├── knowledge.py     # /knowledge/*
│   │   ├── blackboard.py    # /blackboard/*
│   │   └── queue.py         # /queue/*
│   └── models/              # Pydantic request/response schemas
├── orchestrator/            # Core business logic
│   ├── checker.py           # Safety gate (dangerous command detection)
│   ├── decision_log.py      # Audit trail
│   ├── safety.py            # Safety rules engine
│   ├── clarify.py           # Ambiguity resolution
│   ├── knowledge.py         # Brain (cross-session memory)
│   ├── auto_consolidate.py  # Memory consolidation from verify verdicts
│   ├── repair.py            # Brain-assisted repair
│   ├── triage.py            # Escalated task analysis
│   ├── metrics.py           # Eval metrics collection
│   └── reflect.py           # Self-reflection / improvement proposals
├── scripts/                 # CLI entry points
│   ├── agentos.sh           # Main CLI (run, knowledge-read, etc.)
│   ├── guard_contracts.py   # Contract validation (CI)
│   ├── run_eval.py          # Evaluation scoring
│   └── install-autostart.sh # LaunchAgent setup
├── tests/                   # pytest suite
├── data/                    # Runtime databases
│   ├── decisions.db         # Audit log
│   ├── brain.db             # Knowledge store
│   └── blackboard.db        # Session state
├── docs/                    # Documentation
└── .scream-code/            # Agent session handoff & goals
    ├── handoff-next-session.md
    ├── core-goal.md
    └── skill-sources/       # Source of truth for scream skills
```

## Development Commands

```bash
# Setup
uv sync --extra dev

# Run server
./scripts/agentos.sh up

# Run tests
uv run pytest tests/ -q

# Run contracts
uv run python scripts/guard_contracts.py

# Code style
uv run ruff check .
uv run ruff format .
```

## Rules

1. **Never modify** `orchestrator/checker.py`, `decision_log.py`, `safety.py`, or `clarify.py` without explicit user approval.
2. **All commits/pushes** to main require user confirmation.
3. **Tests must pass** before marking any task complete.
4. **Output Traditional Chinese** when communicating with the user.
5. **Read `.scream-code/handoff-next-session.md`** at session start for current progress.
6. **Read `.scream-code/core-goal.md`** — it overrides all other instructions.
7. **Skill sources** in `.scream-code/skill-sources/` are the ground truth for agent skills — keep them in sync with code changes.

## Endpoints Reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Server health check |
| POST | `/task/make` | One-shot maker call |
| POST | `/task/verify` | Run pytest + consolidate results → brain |
| GET/POST | `/knowledge/{key}` | Read/write brain entry |
| GET | `/knowledge/search?q=` | Full-text search |
| GET/POST | `/blackboard/{key}` | Read/write session state |
| POST | `/queue/push` | Enqueue background task |
| GET | `/queue/status` | Queue status |

## Updating AGENTS.md / CLAUDE.md

When architecture changes (new modules, endpoints, or rules):
1. Update AGENTS.md (agent onboarding + workflow)
2. Update CLAUDE.md (tech stack + architecture + commands)
3. Update skill sources in `.scream-code/skill-sources/`
