"""FastAPI gateway. Tauri frontend talks to this via HTTP + WebSocket."""
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from contracts.task_spec import TaskSpec
from align.core import parse_answers_to_spec, ALIGN_QUESTIONS
from orchestrator.loop import run as run_loop
from orchestrator.maker import make as run_maker

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# In-memory session store (single-user desktop app, no persistence needed)
sessions: dict[str, dict] = {}
ws_clients: dict[str, WebSocket] = {}


# ── request / response models ────────────────────────────────────────────

class TaskRequest(BaseModel):
    task: str

    @field_validator("task")
    @classmethod
    def task_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("task must not be empty")
        return v


class ApproveRequest(BaseModel):
    session_id: str
    spec: dict             # TaskSpec fields confirmed by user


class DeliverRequest(BaseModel):
    session_id: str
    accepted: bool
    feedback: str = ""


class SettingsPayload(BaseModel):
    maker_model: str = "agnes"
    checker_model: str = "gemini-flash"
    checker_fallbacks: list[str] = ["agnes"]
    max_rounds: int = 5
    temperature: float = 0.7
    max_tokens: int = 2048
    system_prompt: str = ""
    mcp_servers: list[dict] = []
    api_keys: dict[str, str] = {}


SETTINGS_PATH = Path(__file__).parent.parent / "data" / "settings.json"


def _load_settings() -> dict:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text())
    return SettingsPayload().model_dump()


def _save_settings(data: dict):
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2))


# ── helpers ──────────────────────────────────────────────────────────────

async def push(session_id: str, event: str, data: Any):
    ws = ws_clients.get(session_id)
    if ws:
        try:
            await ws.send_text(json.dumps({"event": event, "data": data}))
        except Exception:
            pass


# ── routes ───────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"ok": True}


@app.get("/settings")
def get_settings():
    return _load_settings()


@app.post("/settings")
def save_settings(payload: SettingsPayload):
    data = payload.model_dump()
    # write non-empty api keys to environment (runtime only, not .env file)
    for key, val in data.get("api_keys", {}).items():
        if val:
            os.environ[f"{key.upper()}_API_KEY"] = val
    _save_settings(data)
    return {"ok": True}


@app.get("/models")
def list_models():
    from orchestrator.model_registry import ALIASES
    return {"models": ALIASES}


def _classify_intent(task: str) -> str:
    """Returns 'direct' for conversational/simple tasks, 'task' for complex ones."""
    from router.classifier import llm_classify
    from router.rules import TaskType
    t = task.strip()

    # Heuristic fast path — obvious questions
    lo = t.lower()
    question_starters = (
        "什麼", "是什麼", "解釋", "說明", "如何", "為什麼", "怎麼", "請問",
        "what", "how", "why", "explain", "describe", "summarize", "who", "when", "where",
        "tell me", "show me",
    )
    task_verbs = (
        "實作", "建立", "實現", "開發", "設計", "寫一個", "建一個", "幫我做",
        "build", "implement", "create", "develop", "write a", "set up", "deploy",
    )
    looks_like_question = (
        t.endswith("?") or t.endswith("？")
        or any(lo.startswith(p) or lo.endswith("是什麼") for p in question_starters)
    )
    looks_like_task = any(v in lo for v in task_verbs)

    if looks_like_question and not looks_like_task:
        return "direct"

    # LLM classifier for ambiguous cases
    try:
        task_type, confidence = llm_classify(task)
        if task_type in (TaskType.HIGH_FREQ, TaskType.SUMMARY) and confidence >= 0.5:
            return "direct"
        if task_type == TaskType.ARCHITECTURE and confidence >= 0.6:
            return "task"
        # Short simple feature requests → direct
        if task_type == TaskType.FEATURE and confidence >= 0.7 and len(t) < 80:
            return "direct"
    except Exception:
        pass

    # Default: if task is short and doesn't look like a build task → direct
    if len(t) < 60 and not looks_like_task:
        return "direct"

    return "task"


def _make_direct_spec(task: str) -> TaskSpec:
    """Minimal spec for a direct-answer task (single Maker pass)."""
    return TaskSpec(
        why=task,
        io_example={"input": task, "expected_output": "clear helpful response"},
        taste=[],
        boundaries=[],
        stop_on_metric="quality",
        max_rounds=1,
    )


@app.post("/chat")
async def chat_endpoint(req: TaskRequest):
    """Smart routing: direct answer or alignment flow."""
    session_id = str(uuid.uuid4())[:8]
    intent = _classify_intent(req.task)

    if intent == "direct":
        spec = _make_direct_spec(req.task)
        sessions[session_id] = {"raw_task": req.task, "status": "running", "spec": spec.model_dump()}
        asyncio.create_task(_run_direct_and_push(session_id, spec))
        return {"session_id": session_id, "mode": "direct"}
    else:
        sessions[session_id] = {"raw_task": req.task, "status": "aligning"}
        return {"session_id": session_id, "mode": "align", "questions": ALIGN_QUESTIONS}


async def _run_direct_and_push(session_id: str, spec: TaskSpec):
    """Single Maker call — no checker loop. For conversational / simple tasks."""
    loop = asyncio.get_event_loop()

    def on_token(token: str):
        asyncio.run_coroutine_threadsafe(push(session_id, "token", {"text": token}), loop)

    try:
        output = await asyncio.to_thread(run_maker, spec, "", 1, on_token)
        sessions[session_id]["status"] = "done"
        sessions[session_id]["output"] = output
        await push(session_id, "result", {
            "status": "done", "output": output,
            "rounds": 1, "final_score": None, "history": [],
        })
    except Exception as e:
        await push(session_id, "error", {"msg": str(e)})
        sessions[session_id]["status"] = "error"


@app.post("/task/submit")
async def submit_task(req: TaskRequest):
    """Legacy: P Gate step 1. Prefer /chat for new callers."""
    session_id = str(uuid.uuid4())[:8]
    sessions[session_id] = {"raw_task": req.task, "status": "aligning"}
    return {"session_id": session_id, "questions": ALIGN_QUESTIONS}


@app.post("/task/approve")
async def approve_task(req: ApproveRequest):
    """P Gate step 2: user confirms spec → kick off Maker/Checker loop."""
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(404, "session not found")

    a = dict(req.spec)
    if not a.get("why"):
        a["why"] = session["raw_task"]
    spec = parse_answers_to_spec(a)

    sessions[req.session_id]["spec"] = spec.model_dump()
    sessions[req.session_id]["status"] = "running"

    # Run loop in background, push updates via WebSocket
    asyncio.create_task(_run_and_push(req.session_id, spec))
    return {"ok": True, "session_id": req.session_id}


async def _run_and_push(session_id: str, spec: TaskSpec):
    await push(session_id, "status", {"msg": "Maker/Checker loop started", "status": "running"})

    loop = asyncio.get_event_loop()

    def on_token(token: str):
        asyncio.run_coroutine_threadsafe(
            push(session_id, "token", {"text": token}), loop
        )

    def on_round_start(round_n: int):
        asyncio.run_coroutine_threadsafe(
            push(session_id, "round_start", {"round": round_n}), loop
        )

    try:
        result = await asyncio.to_thread(run_loop, spec,
                                         on_token=on_token,
                                         on_round_start=on_round_start)
        sessions[session_id]["result"] = result
        sessions[session_id]["status"] = result["status"]
        await push(session_id, "result", result)
    except Exception as e:
        await push(session_id, "error", {"msg": str(e)})
        sessions[session_id]["status"] = "error"


@app.post("/task/deliver")
async def deliver(req: DeliverRequest):
    """A Gate: user accepts or rejects final output."""
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(404, "session not found")
    session["delivered"] = req.accepted
    session["deliver_feedback"] = req.feedback
    return {"ok": True, "accepted": req.accepted}


@app.get("/session/{session_id}")
def get_session(session_id: str):
    s = sessions.get(session_id)
    if not s:
        raise HTTPException(404, "session not found")
    return s


@app.get("/cost")
def get_cost():
    """Return running cost from SQLite decision log."""
    import sqlite3
    db = Path(__file__).parent.parent / "data" / "decisions.db"
    if not db.exists():
        return {"total_usd": 0.0, "calls": 0}
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(cost_usd),0) FROM routing_log"
    ).fetchone()
    conn.close()
    return {"total_usd": round(row[1], 6), "calls": row[0]}


# ── WebSocket ─────────────────────────────────────────────────────────────

@app.websocket("/ws/{session_id}")
async def ws_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    ws_clients[session_id] = websocket
    try:
        while True:
            await websocket.receive_text()  # keep alive
    except WebSocketDisconnect:
        ws_clients.pop(session_id, None)
