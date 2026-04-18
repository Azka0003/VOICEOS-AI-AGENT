import os
import json
import base64
import asyncio
from urllib.parse import quote
from fastapi import FastAPI, WebSocket, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from tools.twilio_tool import twilio_tool
from tools.deepgram_tool import DeepgramVoiceAgent
from tools.hitl_tool import hitl_manager
from tools.llm_router import llm_router
from agents.invoice_agent import InvoiceAgent
from startup import seed_chromadb
from contextlib import asynccontextmanager

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_chromadb()
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/call/start")
async def start_call(to_number: str, client_name: str):
    # 1. Prepare initial components
    script_prompt = f"Generate a 1-sentence greeting for {client_name} about an overdue invoice."
    script = llm_router.invoke(
        prompt=script_prompt,
        mode="generation",
        agent_name="main_api"
    )

    # 2. Fetch real data from Invoice Agent to feed HITL Context
    inv_agent = InvoiceAgent()
    client_data = inv_agent.get_client_data(client_name) or {}
    
    invoice_context = {
        "client": client_name,
        "invoice_id": client_data.get("latest_invoice_id", "INV_UNKNOWN"),
        "amount": client_data.get("total_due", 0),
        "days_overdue": client_data.get("max_days_overdue", 0),
        "risk_score": client_data.get("risk_score", 50),
        "dispute_flag": client_data.get("dispute_flag", False),
        "contact_name": client_data.get("contact_info", {}).get("name", ""),
        "contact_phone": to_number,
        "contact_email": client_data.get("contact_info", {}).get("email", ""),
        "next_action": client_data.get("next_action", "")
    }
    comms_history = client_data.get("comms_history", [])
    
    # 3. Simulate the requested 'planned_action' string format to match compute_confidence checks
    planned_action = f"Call {to_number} to execute friendly_reminder script: {script}"

    # 4. Smart HITL Evaluation
    resolution = await hitl_manager.evaluate_and_wait(invoice_context, comms_history, planned_action)

    # 5. Handle Negative Resolution Choices
    if resolution and resolution.get("option_id") in ["skip", "cancel"]:
        return {
            "status": "cancelled", 
            "reason": f"Action stopped by human. Decision: {resolution.get('option_id')}"
        }

    # 6. Execute Twilio Dial
    base_url = os.getenv("BASE_URL")
    safe_client = quote(client_name)
    twiml_url = f"{base_url}/call/twiml-initial?client_name={safe_client}"
    
    call_sid = twilio_tool.make_call(to_number, twiml_url)

    return {"status": "calling", "call_sid": call_sid}

@app.post("/call/twiml-initial")
async def twiml_initial(client_name: str = ""):
    domain = os.getenv("BASE_URL", "").replace("https://", "").replace("http://", "")
    safe_client = quote(client_name)
    
    response_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="wss://{domain}/twilio-stream?client_name={safe_client}" />
    </Connect>
</Response>"""
    return Response(content=response_xml, media_type="application/xml")

@app.websocket("/twilio-stream")
async def websocket_endpoint(websocket: WebSocket, client_name: str = ""):
    await websocket.accept()

    # --- FETCH LIVE DATA FROM DATABASE ---
    inv_agent = InvoiceAgent()
    client_data = inv_agent.get_client_data(client_name)

    if client_data:
        total_due = client_data.get('total_due', 0)
        days_overdue = client_data.get('max_days_overdue', 0)
        contact = client_data.get('contact_info', {}).get('name') or "Sir/Madam"
        briefing = client_data.get('_full_context', {}).get('briefing_text', '')

        system_prompt = (
            f"You are DebtPilot, an AI collections agent calling on behalf of an Indian firm. "
            f"You are NOT a general assistant — you have one job: collect payment or get a firm commitment with a date. "
            f"You are calling {client_name}. The contact person is {contact}. "
            f"Total overdue balance: ₹{total_due:,} ({days_overdue} days overdue). "
            f"\n\nFULL CLIENT BRIEFING (your ground truth — follow this precisely):\n{briefing}"
            f"\n\nCALL RULES:\n"
            f"- Start by asking to speak with {contact} by name. Verify you have the right person before discussing any financial details.\n"
            f"- If it is {contact}: proceed with the briefing above.\n"
            f"- If it is NOT {contact}: apologise politely, ask when {contact} can be reached, then say goodbye.\n"
            f"- If no answer / wrong number: apologise and end the call.\n"
            f"- Keep responses short and conversational — one point at a time. Pause and listen.\n"
            f"- Never say 'How can I help you?' — YOU are making this call, not receiving one.\n"
            f"- Never invent invoice numbers, amounts, or dates. Use only what is in the briefing above.\n"
            f"- Your goal is a specific payment date commitment, not a vague promise.\n"
            f"- End the call politely once you have a commitment or a clear refusal."
        )
        greeting = f"Hello, am I speaking with {contact} from {client_name}?"
    else:
        system_prompt = "You are a professional voice assistant on a phone call. Keep responses short."
        greeting = "Hello, how can I help you today?"

    agent = DeepgramVoiceAgent(
        twilio_ws=websocket,
        system_prompt=system_prompt,
        greeting=greeting
    )

    agent_task = asyncio.create_task(agent.run())

    try:
        while True:
            data = await websocket.receive_text()
            packet = json.loads(data)

            event = packet.get("event")

            if event == "start":
                stream_sid = packet['start']['streamSid']
                agent.set_stream_sid(stream_sid)
                print(f"[TWILIO] Stream started: {stream_sid}")

            elif event == "media":
                audio_bytes = base64.b64decode(packet["media"]["payload"])
                agent.send_audio(audio_bytes)

            elif event == "stop":
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

# --- HITL Endpoints ---
@app.get("/hitl/pending")
async def get_pending():
    return hitl_manager.get_all_pending()

@app.post("/hitl/approve/{checkpoint_id}")
async def approve_task(checkpoint_id: str, data: dict):
    hitl_manager.resolve_checkpoint(checkpoint_id, data)
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)