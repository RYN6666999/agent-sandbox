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
from align.core import parse_answers_to_spec, synthesize_task_brief, ALIGN_QUESTIONS
from orchestrator.loop import run as run_loop
from orchestrator.maker import make as run_maker
from orchestrator import decision_log

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# In-memory session store (single-user desktop app, no persistence needed)
sessions: dict[str, dict] = {}
ws_clients: dict[str, WebSocket] = {}


# ── request / response models ────────────────────────────────────────────

class TaskRequest(BaseModel):
    task: str
    forced_mode: str | None = None   # "direct" | "align" | "loop" — skips routing

    @field_validator("task")
    @classmethod
    def task_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("task must not be empty")
        return v


class ConverseRequest(BaseModel):
    message: str
    history: list[dict] = []   # [{role: "user"|"system", text: str}, ...]

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be empty")
        return v


class ApproveRequest(BaseModel):
    session_id: str
    spec: dict             # TaskSpec fields confirmed by user


class DeliverRequest(BaseModel):
    session_id: str
    accepted: bool
    feedback: str = ""


class SettingsPayload(BaseModel):
    plan_model: str = "openrouter-classifier"    # D16: classifier / routing intent
    maker_model: str = "gpt-oss-120b"             # D17: strong coding model via OpenRouter
    converse_model: str = "agnes"                 # fast model for /converse chat path
    checker_model: str = "gemini-flash"          # LLM path only; pytest path uses no model
    checker_fallbacks: list[str] = ["agnes"]
    routing_confidence_threshold: float = 0.8   # kept for reference; D11 now uses 3-way intent
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


def _classify_intent(task: str) -> dict:
    """Return intent-gate decision trace for API-level direct vs align routing.

    Two-stage:
    1. Heuristic: pure-question → direct (trusted, no model needed).
    2. LLM 3-way routing intent: answer/code/unclear.
       unclear → decision="clarify_routing" (D11).
       Fallback error also returns unclear (safer to ask than guess).
    """
    from router.classifier import routing_intent

    t = task.strip()
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
    matched_question = next((p for p in question_starters if lo.startswith(p)), None)
    matched_task_verb = next((v for v in task_verbs if v in lo), None)
    looks_like_question = (
        t.endswith("?") or t.endswith("？") or matched_question is not None or lo.endswith("是什麼")
    )
    looks_like_task = matched_task_verb is not None

    common_details = {
        "looks_like_question": looks_like_question,
        "looks_like_task": looks_like_task,
        "task_length": len(t),
    }

    # Heuristic fast-path: pure question, no build signal → direct (D11: trusted)
    if looks_like_question and not looks_like_task:
        return {
            "decision": "direct",
            "decision_source": "heuristic",
            "matched_keyword": matched_question or ("?" if t.endswith("?") or t.endswith("？") else "是什麼"),
            "confidence": 0.95,
            "classifier_model": None,
            "fallback_reason": None,
            "details": {**common_details, "heuristic_reason": "question_without_build_signal"},
        }

    # LLM 3-way routing intent (D11: unclear → clarify_routing)
    ri = routing_intent(task)
    ri_details = {
        **common_details,
        "routing_category": ri.category,
        "routing_reason": ri.reason,
        "routing_source": ri.source,
    }

    decision_map = {"answer": "direct", "code": "align", "unclear": "clarify_routing"}
    decision = decision_map.get(ri.category, "clarify_routing")

    return {
        "decision": decision,
        "decision_source": ri.source,
        "matched_keyword": matched_task_verb,
        "confidence": 0.9 if ri.category in ("answer", "code") and ri.source == "llm" else 0.5,
        "classifier_model": ri.classifier_model,
        "fallback_reason": ri.reason if ri.source == "fallback" else None,
        "details": ri_details,
    }


def _request_id_for(session_id: str) -> str:
    return sessions.get(session_id, {}).get("request_id", session_id)


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


_or_free_cache: list[str] = []
_or_free_fetched_at: float = 0.0
_OR_CACHE_TTL = 3600.0  # 1 hour


def _fetch_openrouter_free(api_key: str) -> list[str]:
    import time
    import urllib.request
    global _or_free_cache, _or_free_fetched_at

    now = time.time()
    if _or_free_cache and now - _or_free_fetched_at < _OR_CACHE_TTL:
        return _or_free_cache

    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}", "HTTP-Referer": "http://localhost"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        free = [
            f"openrouter/{m['id']}"
            for m in data.get("data", [])
            if str(m.get("pricing", {}).get("prompt", "1")) == "0"
        ]
        _or_free_cache = sorted(free)
        _or_free_fetched_at = now
    except Exception:
        pass  # keep stale cache or return empty

    return _or_free_cache


@app.get("/models")
def list_models():
    from orchestrator.model_registry import PAID_MODELS
    settings = _load_settings()
    api_key = settings.get("api_keys", {}).get("openrouter") or os.environ.get("OPENROUTER_API_KEY", "")
    free = _fetch_openrouter_free(api_key) if api_key else []
    return {"free": free, "paid": PAID_MODELS}


def _make_loop_spec(task: str) -> TaskSpec:
    """Forced full Maker/Checker loop — skips align, keeps raw task as-is."""
    return TaskSpec(
        why=task,
        io_example={"input": task, "expected_output": "working code with passing tests"},
        taste=[
            "Output EXACTLY ONE ```python ... ``` fenced code block. No other code blocks.",
            "The single block must contain BOTH the implementation AND the pytest tests.",
            "NEVER use 'from solution import ...' or 'import solution' — "
            "define ALL functions in the same block as the tests.",
            "Tests must call the function directly, e.g. `assert flatten([1,[2]]) == [1,2]`.",
        ],
        boundaries=[],
        stop_on_metric="correctness and completeness",
        max_rounds=5,
    )


def _make_investigate_spec(task: str) -> TaskSpec:
    """Investigation task — delegates to Claude Code CLI (uses Pro + all tools)."""
    return TaskSpec(
        why=task,
        io_example={"input": task, "expected_output": "findings with concrete evidence and root cause"},
        taste=[
            "Use all available tools (browser, file system, bash) to gather real evidence.",
            "Report specific findings: file paths, line numbers, timestamps, exact values.",
            "State the root cause clearly at the end.",
        ],
        boundaries=["Do not guess without evidence", "Do not ask clarifying questions — investigate and report"],
        stop_on_metric="concrete findings with evidence",
        max_rounds=2,
        executor="claude-code",
    )


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


@app.post("/converse")
async def converse_endpoint(req: ConverseRequest):
    """Chat path: blocking LLM call, returns full reply in HTTP body. No WS needed."""
    import litellm
    from orchestrator.model_registry import resolve as _resolve

    CONVERSE_TIMEOUT = 60  # seconds

    lm_messages = []
    for m in req.history[-10:]:
        role = "user" if m.get("role") == "user" else "assistant"
        lm_messages.append({"role": role, "content": m.get("text", "")})
    lm_messages.append({"role": "user", "content": req.message})

    try:
        converse_model = _load_settings().get("converse_model", "agnes")
        params = _resolve(converse_model)
        resp = await asyncio.wait_for(
            asyncio.to_thread(
                litellm.completion,
                messages=lm_messages,
                max_tokens=1024,
                temperature=0.7,
                **params,
            ),
            timeout=CONVERSE_TIMEOUT,
        )
        reply = resp.choices[0].message.content.strip()
    except asyncio.TimeoutError:
        reply = f"⏱ 回應逾時（>{CONVERSE_TIMEOUT}s），請再試一次。"
    except Exception as e:
        reply = f"⚠️ 發生錯誤：{e}"

    return {"reply": reply, "mode": "converse"}


_ROUTING_CLARIFY_QUESTION = (
    "我不確定這個任務是要我 (A) 直接回答就好，"
    "還是 (B) 做出可驗收的成果（寫程式／附測試）？"
    "請選 A 或 B。"
)


@app.post("/chat")
async def chat_endpoint(req: TaskRequest):
    """Smart routing: safety → clarify → confidence-gated intent → direct/align."""
    session_id = str(uuid.uuid4())[:8]

    # Safety gate ALWAYS runs first — even for forced_mode requests (D3 red line)
    from orchestrator.safety import is_dangerous
    dangerous, triggers = is_dangerous(req.task)
    if dangerous:
        sessions[session_id] = {"raw_task": req.task, "status": "confirm_dangerous"}
        return {"session_id": session_id, "mode": "confirm_dangerous", "triggers": triggers}

    # forced_mode == "loop": user explicitly chose full Maker/Checker, skip clarify + align
    if req.forced_mode == "loop":
        request_id = session_id
        spec = _make_loop_spec(req.task)
        decision_log.record_request_trace(
            request_id=request_id,
            session_id=session_id,
            entrypoint="chat",
            raw_task=req.task,
            latest_status="running",
            notes={"forced_mode": "loop"},
        )
        decision_log.record_intent_gate(
            request_id=request_id,
            session_id=session_id,
            decision="loop",
            decision_source="user_forced",
            confidence=1.0,
            details={"reason": "user picked override → direct full loop"},
        )
        sessions[session_id] = {
            "request_id": request_id,
            "raw_task": req.task,
            "status": "running",
            "spec": spec.model_dump(),
        }
        decision_log.update_request_status(request_id, "running")
        asyncio.create_task(_run_and_push(session_id, spec))
        return {"session_id": session_id, "mode": "loop"}

    # forced_mode == "investigate": delegate to Claude Code CLI
    if req.forced_mode == "investigate":
        request_id = session_id
        spec = _make_investigate_spec(req.task)
        decision_log.record_request_trace(
            request_id=request_id,
            session_id=session_id,
            entrypoint="chat",
            raw_task=req.task,
            latest_status="running",
            notes={"forced_mode": "investigate"},
        )
        sessions[session_id] = {
            "request_id": request_id,
            "raw_task": req.task,
            "status": "running",
            "spec": spec.model_dump(),
        }
        decision_log.update_request_status(request_id, "running")
        asyncio.create_task(_run_and_push(session_id, spec))
        return {"session_id": session_id, "mode": "investigate"}

    # forced_mode: user answered clarify_routing question — skip re-routing
    if req.forced_mode in ("direct", "align"):
        request_id = session_id
        decision_log.record_request_trace(
            request_id=request_id,
            session_id=session_id,
            entrypoint="chat_forced",
            raw_task=req.task,
            latest_status="pending_intent_gate",
            notes={"forced_mode": req.forced_mode},
        )
        decision_log.record_intent_gate(
            request_id=request_id,
            session_id=session_id,
            decision=req.forced_mode,
            decision_source="user_clarify_routing",
            confidence=1.0,
            details={"forced_mode": req.forced_mode},
        )
        if req.forced_mode == "direct":
            spec = _make_direct_spec(req.task)
            sessions[session_id] = {"request_id": request_id, "raw_task": req.task,
                                     "status": "running", "spec": spec.model_dump()}
            decision_log.update_request_status(request_id, "running")
            asyncio.create_task(_run_direct_and_push(session_id, spec))
            return {"session_id": session_id, "mode": "direct"}
        sessions[session_id] = {"request_id": request_id, "raw_task": req.task, "status": "aligning"}
        decision_log.update_request_status(request_id, "aligning")
        return {"session_id": session_id, "mode": "align", "questions": ALIGN_QUESTIONS}

    # Clarification gate — 0–1 LLM calls (content ambiguity, not routing ambiguity)
    from orchestrator.clarify import needs_clarification
    should_clarify, question = needs_clarification(req.task)
    if should_clarify:
        sessions[session_id] = {"raw_task": req.task, "status": "clarifying"}
        return {"session_id": session_id, "mode": "clarify", "question": question}

    request_id = session_id
    decision_log.record_request_trace(
        request_id=request_id,
        session_id=session_id,
        entrypoint="chat",
        raw_task=req.task,
        latest_status="pending_intent_gate",
        notes={"request_id_equals_session_id": True},
    )

    intent = _classify_intent(req.task)

    # D11: clarify_routing comes directly from _classify_intent (unclear category)
    if intent["decision"] == "clarify_routing":
        decision_log.record_intent_gate(
            request_id=request_id,
            session_id=session_id,
            decision="clarify_routing",
            decision_source=intent["decision_source"],
            matched_keyword=intent.get("matched_keyword"),
            confidence=intent.get("confidence"),
            classifier_model=intent.get("classifier_model"),
            fallback_reason=intent.get("fallback_reason"),
            details={**intent.get("details", {}), "trigger": "routing_intent_unclear"},
        )
        sessions[session_id] = {"raw_task": req.task, "status": "clarify_routing"}
        return {
            "session_id": session_id,
            "mode": "clarify_routing",
            "question": _ROUTING_CLARIFY_QUESTION,
            "options": ["A", "B"],
        }

    decision_log.record_intent_gate(
        request_id=request_id,
        session_id=session_id,
        decision=intent["decision"],
        decision_source=intent["decision_source"],
        matched_keyword=intent.get("matched_keyword"),
        confidence=intent.get("confidence"),
        classifier_model=intent.get("classifier_model"),
        fallback_reason=intent.get("fallback_reason"),
        details=intent.get("details"),
    )

    if intent["decision"] == "direct":
        spec = _make_direct_spec(req.task)
        sessions[session_id] = {
            "request_id": request_id,
            "raw_task": req.task,
            "status": "running",
            "spec": spec.model_dump(),
        }
        decision_log.update_request_status(request_id, "running")
        asyncio.create_task(_run_direct_and_push(session_id, spec))
        return {"session_id": session_id, "mode": "direct"}

    sessions[session_id] = {"request_id": request_id, "raw_task": req.task, "status": "aligning"}
    decision_log.update_request_status(request_id, "aligning")
    return {"session_id": session_id, "mode": "align", "questions": ALIGN_QUESTIONS}


async def _run_direct_and_push(session_id: str, spec: TaskSpec):
    """Single Maker call — no checker loop. For conversational / simple tasks."""
    loop = asyncio.get_event_loop()
    request_id = _request_id_for(session_id)

    def on_token(token: str):
        asyncio.run_coroutine_threadsafe(push(session_id, "token", {"text": token}), loop)

    try:
        output = await asyncio.to_thread(
            run_maker,
            spec,
            "",
            1,
            on_token,
            request_id=request_id,
            session_id=session_id,
        )
        sessions[session_id]["status"] = "done"
        sessions[session_id]["output"] = output
        decision_log.update_request_status(request_id, "done")
        await push(session_id, "result", {
            "status": "done", "output": output,
            "rounds": 1, "final_score": None, "history": [],
        })
    except Exception as e:
        await push(session_id, "error", {"msg": str(e)})
        sessions[session_id]["status"] = "error"
        decision_log.update_request_status(request_id, "error")


@app.post("/task/submit")
async def submit_task(req: TaskRequest):
    """Legacy: P Gate step 1. Prefer /chat for new callers."""
    session_id = str(uuid.uuid4())[:8]
    request_id = session_id
    decision_log.record_request_trace(
        request_id=request_id,
        session_id=session_id,
        entrypoint="task_submit",
        raw_task=req.task,
        latest_status="aligning",
        notes={"request_id_equals_session_id": True, "legacy_entrypoint": True},
    )
    decision_log.record_intent_gate(
        request_id=request_id,
        session_id=session_id,
        decision="align",
        decision_source="legacy_submit",
        confidence=1.0,
        details={"reason": "legacy endpoint always enters align"},
    )
    sessions[session_id] = {"request_id": request_id, "raw_task": req.task, "status": "aligning"}
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

    # Safety gate — same function as /chat, covers answers filled during align
    from orchestrator.safety import is_dangerous
    combined_text = " ".join(str(v) for v in a.values())
    dangerous, triggers = is_dangerous(combined_text)
    if dangerous:
        return {"ok": False, "mode": "confirm_dangerous", "triggers": triggers,
                "session_id": req.session_id}

    spec = parse_answers_to_spec(a)

    # Synthesize a clear executable task brief and use it as the primary task description
    brief = synthesize_task_brief(a)
    spec = spec.model_copy(update={"why": brief})

    request_id = session.get("request_id", req.session_id)
    sessions[req.session_id]["spec"] = spec.model_dump()
    sessions[req.session_id]["status"] = "running"
    decision_log.update_request_status(request_id, "running")

    # Run loop in background, push updates via WebSocket
    asyncio.create_task(_run_and_push(req.session_id, spec))
    return {"ok": True, "session_id": req.session_id}


async def _run_and_push(session_id: str, spec: TaskSpec):
    await push(session_id, "status", {"msg": "Maker/Checker loop started", "status": "running"})

    loop = asyncio.get_event_loop()
    request_id = _request_id_for(session_id)

    def on_token(token: str):
        asyncio.run_coroutine_threadsafe(
            push(session_id, "token", {"text": token}), loop
        )

    maker_model = _load_settings().get("maker_model", "unknown")

    def on_round_start(round_n: int):
        asyncio.run_coroutine_threadsafe(
            push(session_id, "round_start", {"round": round_n, "model": maker_model}), loop
        )

    try:
        result = await asyncio.to_thread(
            run_loop,
            spec,
            on_token=on_token,
            on_round_start=on_round_start,
            request_id=request_id,
            session_id=session_id,
        )
        sessions[session_id]["result"] = result
        sessions[session_id]["status"] = result["status"]
        decision_log.update_request_status(request_id, result["status"])
        await push(session_id, "result", result)
    except Exception as e:
        await push(session_id, "error", {"msg": str(e)})
        sessions[session_id]["status"] = "error"
        decision_log.update_request_status(request_id, "error")


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
    """Return current routing event count from SQLite decision log."""
    import sqlite3

    decision_log.ensure_schema()
    db = decision_log.get_db_path()
    if not db.exists():
        return {"total_usd": 0.0, "calls": 0}

    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM routing_events WHERE event_type = 'execution_route'"
        ).fetchone()
    finally:
        conn.close()
    return {"total_usd": 0.0, "calls": row[0] if row else 0}


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
