"""
main.py — DebtPilot FastAPI Backend

Endpoints:
  GET  /                       → health check
  POST /batch/run              → trigger full autonomous batch (dashboard button)
  GET  /batch/status           → latest batch result
  GET  /events                 → SSE stream for live frontend updates
  GET  /dashboard/data         → portfolio summary + recent lineage log
  GET  /call/start             → manual single-client call (legacy)
  POST /call/twiml-initial     → Twilio TwiML webhook
  WS   /twilio-stream          → Deepgram bridge
  POST /call/outcome           → called by agent after call ends → Excel write-back
  GET  /hitl/pending           → list pending approvals
  POST /hitl/approve/{id}      → resolve a HITL checkpoint
"""

import os, json, asyncio, base64
from urllib.parse import quote
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

from tools.twilio_tool import twilio_tool
from tools.deepgram_tool import DeepgramVoiceAgent
from tools.hitl_tool import hitl_manager
from tools.llm_router import llm_router
from tools.lineage_logger import lineage_logger
from tools.excel_tool import excel_tool
from agents.invoice_agent import InvoiceAgent
from agents.action_agent import ActionAgent
from startup import seed_chromadb

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# SSE event bus — broadcasts to all connected dashboard clients
# ─────────────────────────────────────────────────────────────────────────────

_sse_subscribers: list[asyncio.Queue] = []

async def broadcast(event: dict):
    """Push a JSON event to every SSE subscriber."""
    dead = []
    for q in _sse_subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _sse_subscribers.remove(q)

# ─────────────────────────────────────────────────────────────────────────────
# Active call registry  {call_sid: client_name}
# ─────────────────────────────────────────────────────────────────────────────
_active_calls: dict[str, str] = {}

# ─────────────────────────────────────────────────────────────────────────────
# Batch state
# ─────────────────────────────────────────────────────────────────────────────
_batch_running = False
_last_batch_result: dict = {}

# ─────────────────────────────────────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_chromadb()

    # Optional: APScheduler for daily 9am auto-run
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler()
        scheduler.add_job(_run_batch_job, "cron", hour=9, minute=0, id="daily_batch")
        scheduler.start()
        print("[SCHEDULER] Daily batch job scheduled at 09:00.")
    except ImportError:
        print("[SCHEDULER] apscheduler not installed — skipping scheduled job. "
              "Run: pip install apscheduler --break-system-packages")
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

invoice_agent = InvoiceAgent()
action_agent  = ActionAgent()

# ─────────────────────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
async def health():
    return {"status": "ok", "service": "DebtPilot", "timestamp": datetime.now(timezone.utc).isoformat()}

# ─────────────────────────────────────────────────────────────────────────────
# Dashboard data
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/dashboard/data")
async def dashboard_data():
    """Returns everything the frontend needs in one call."""
    try:
        portfolio = invoice_agent.get_portfolio_summary()
        clients = invoice_agent.get_priority_clients()
        recent_log = lineage_logger.get_recent(30)
        hitl_pending = hitl_manager.get_all_pending()
        return {
            "portfolio": portfolio,
            "clients": clients,
            "lineage_log": recent_log,
            "hitl_pending": hitl_pending,
            "batch_running": _batch_running,
            "last_batch": _last_batch_result,
            "active_calls": _active_calls,
        }
    except Exception as e:
        return {"error": str(e)}

# ─────────────────────────────────────────────────────────────────────────────
# SSE stream — live updates to dashboard
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/events")
async def sse_stream(request: Request):
    """Server-Sent Events stream. Frontend connects once and gets live updates."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _sse_subscribers.append(q)

    async def generator():
        try:
            # Send initial state immediately on connect
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield "data: {\"type\":\"ping\"}\n\n"  # keep-alive
        finally:
            if q in _sse_subscribers:
                _sse_subscribers.remove(q)

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ─────────────────────────────────────────────────────────────────────────────
# Autonomous batch
# ─────────────────────────────────────────────────────────────────────────────

async def _run_batch_job():
    """Core batch logic — called by scheduler and by POST /batch/run."""
    global _batch_running, _last_batch_result
    if _batch_running:
        return {"status": "already_running"}

    _batch_running = True
    await broadcast({"type": "batch_start", "timestamp": datetime.now(timezone.utc).isoformat()})

    results = []
    errors  = []

    try:
        clients = invoice_agent.get_priority_clients()
        print(f"[BATCH] Starting. {len(clients)} clients in priority order.")
        await broadcast({"type": "batch_progress", "message": f"Processing {len(clients)} clients...", "total": len(clients)})

        for i, client_info in enumerate(clients):
            client_name = client_info["client"]
            await broadcast({"type": "batch_progress", "message": f"Processing {client_name}...", "current": i+1, "total": len(clients)})

            try:
                context = invoice_agent.get_client_context(client_name)
                if context.get("error"):
                    errors.append({"client": client_name, "error": context["error"]})
                    await broadcast({"type": "client_error", "client": client_name, "error": context["error"]})
                    continue

                # Risk evaluation (simplified inline — avoids circular import)
                from agents.risk_agent import RiskAgent
                risk_result = await RiskAgent().evaluate(context)

                # Action decision + execution
                action_result = await action_agent.decide(context, risk_result)

                lineage_logger.log({
                    "agent": "batch_supervisor",
                    "client": client_name,
                    "risk_score": risk_result.get("risk_score"),
                    "decision": action_result.get("decision"),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })

                results.append({"client": client_name, "action": action_result, "risk": risk_result})
                await broadcast({
                    "type": "client_processed",
                    "client": client_name,
                    "decision": action_result.get("decision"),
                    "risk_label": risk_result.get("risk_label"),
                    "risk_score": risk_result.get("risk_score"),
                })
                print(f"[BATCH] {client_name} → {action_result.get('decision')}")

            except Exception as e:
                errors.append({"client": client_name, "error": str(e)})
                print(f"[BATCH] Error for {client_name}: {e}")

    except Exception as e:
        errors.append({"error": str(e)})
        print(f"[BATCH] Fatal error: {e}")
    finally:
        _batch_running = False
        _last_batch_result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "processed": len(results),
            "errors": len(errors),
            "results": results,
            "errors_detail": errors
        }
        await broadcast({"type": "batch_complete", **_last_batch_result})

    return _last_batch_result


@app.post("/batch/run")
async def trigger_batch():
    """Frontend dashboard button hits this endpoint."""
    if _batch_running:
        return {"status": "already_running", "message": "Batch is already in progress."}
    asyncio.create_task(_run_batch_job())
    return {"status": "started", "message": "Autonomous batch triggered."}

@app.get("/batch/status")
async def batch_status():
    return {"running": _batch_running, "last_result": _last_batch_result}

# ─────────────────────────────────────────────────────────────────────────────
# Call flow
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/call/start")
async def start_call(to_number: str, client_name: str):
    """Manual single-client call trigger (also used by action_agent)."""
    base_url = os.getenv("BASE_URL", "")
    safe_client = quote(client_name)
    twiml_url = f"{base_url}/call/twiml-initial?client_name={safe_client}"
    call_sid = twilio_tool.make_call(to_number, twiml_url)
    if call_sid:
        _active_calls[call_sid] = client_name
        await broadcast({"type": "call_started", "client": client_name, "call_sid": call_sid})
    return {"status": "calling" if call_sid else "failed", "call_sid": call_sid}


@app.post("/call/twiml-initial")
async def twiml_initial(client_name: str = ""):
    domain = os.getenv("BASE_URL", "").replace("https://", "").replace("http://", "")
    safe_client = quote(client_name)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="wss://{domain}/twilio-stream?client_name={safe_client}" />
    </Connect>
</Response>"""
    return Response(content=xml, media_type="application/xml")


@app.websocket("/twilio-stream")
async def websocket_endpoint(websocket: WebSocket, client_name: str = ""):
    await websocket.accept()

    # Build system prompt from live data
    client_data = invoice_agent.get_client_data(client_name)
    if client_data:
        ctx = client_data.get("_full_context", {})
        total_due    = client_data.get("total_due", 0)
        days_overdue = client_data.get("max_days_overdue", 0)
        contact      = client_data.get("contact_info", {}).get("name") or "Sir/Madam"
        briefing     = ctx.get("briefing_text", "")
        system_prompt = (
            f"You are DebtPilot, an AI collections agent. "
            f"You are calling {client_name}. Contact: {contact}. "
            f"Total overdue: ₹{total_due:,} ({days_overdue} days). "
            f"\n\nCLIENT BRIEFING:\n{briefing}"
            f"\n\nRULES: Verify you are speaking with {contact} first. "
            f"Get a specific payment commitment with a date. "
            f"Never invent amounts. End the call politely once resolved."
        )
        greeting = f"Hello, am I speaking with {contact} from {client_name}?"
    else:
        system_prompt = "You are a professional voice assistant on a phone call."
        greeting = "Hello, how can I help you today?"

    # Find the call_sid for this client (for REST hangup)
    call_sid = next((sid for sid, name in _active_calls.items() if name == client_name), None)

    agent = DeepgramVoiceAgent(
        twilio_ws=websocket,
        system_prompt=system_prompt,
        greeting=greeting,
        call_sid=call_sid,
        client_name=client_name,
        event_broadcast=broadcast,
    )
    agent_task = asyncio.create_task(agent.run())

    try:
        while True:
            data = await websocket.receive_text()
            packet = json.loads(data)
            ev = packet.get("event")
            if ev == "start":
                sid = packet["start"]["streamSid"]
                agent.set_stream_sid(sid)
                print(f"[TWILIO] Stream started: {sid}")
            elif ev == "media":
                agent.send_audio(base64.b64decode(packet["media"]["payload"]))
            elif ev == "stop":
                print("[TWILIO] Stream stopped")
                break
    except Exception as e:
        print(f"[WS ERROR] {e}")
    finally:
        await agent.stop()
        agent_task.cancel()
        try:
            await agent_task
        except asyncio.CancelledError:
            pass
        # Clean up active calls registry
        if call_sid and call_sid in _active_calls:
            del _active_calls[call_sid]
        await broadcast({"type": "call_ended", "client": client_name})


@app.post("/call/outcome")
async def call_outcome(data: dict):
    """
    Posted by DeepgramVoiceAgent._finalize_call() when a call ends.
    Writes outcome to Excel + triggers follow-up email if needed.
    """
    client_name       = data.get("client_name", "")
    call_outcome_val  = data.get("call_outcome", "no_response")
    payment_commitment= data.get("payment_commitment")
    notes             = data.get("notes", "")

    print(f"[OUTCOME] {client_name}: {call_outcome_val} | commitment: {payment_commitment}")

    if not client_name:
        return {"status": "error", "message": "client_name required"}

    try:
        # Get client context for Excel update
        context = invoice_agent.get_client_context(client_name)
        if not context.get("error"):
            await action_agent.handle_call_webhook(
                context=context,
                call_outcome=call_outcome_val,
                payment_commitment=payment_commitment,
                notes=notes
            )

        await broadcast({
            "type": "call_outcome",
            "client": client_name,
            "outcome": call_outcome_val,
            "payment_commitment": payment_commitment,
            "notes": notes,
        })

        # Auto-trigger follow-up email if no commitment was made
        if call_outcome_val == "confirmed" and not payment_commitment:
            await broadcast({"type": "agent_action", "message": f"No commitment from {client_name} — scheduling follow-up email."})
            # Email would fire via next batch run with updated next_action

        lineage_logger.log({
            "agent": "call_outcome_webhook",
            "client": client_name,
            "outcome": call_outcome_val,
            "payment_commitment": payment_commitment,
        })

        return {"status": "ok", "client": client_name, "outcome": call_outcome_val}
    except Exception as e:
        print(f"[OUTCOME ERROR] {e}")
        return {"status": "error", "message": str(e)}

# ─────────────────────────────────────────────────────────────────────────────
# HITL
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/hitl/pending")
async def get_pending():
    return hitl_manager.get_all_pending()

@app.post("/hitl/approve/{checkpoint_id}")
async def approve_task(checkpoint_id: str, data: dict):
    hitl_manager.resolve_checkpoint(checkpoint_id, data)
    await broadcast({"type": "hitl_resolved", "checkpoint_id": checkpoint_id, "resolution": data})
    return {"status": "ok"}

# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

# ── Serve frontend ──────────────────────────────────────────────────────────
from fastapi.staticfiles import StaticFiles
import pathlib

_FRONTEND = pathlib.Path(__file__).parent.parent / "frontend"
if _FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")
