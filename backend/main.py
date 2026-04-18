import os
import json
import base64
import asyncio
from urllib.parse import quote # Added for URL encoding
from fastapi import FastAPI, WebSocket, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from tools.twilio_tool import twilio_tool
from tools.deepgram_tool import DeepgramVoiceAgent
from tools.hitl_tool import hitl_manager
from tools.llm_router import llm_router

# UPDATE: Import the InvoiceAgent to fetch real data
from agents.invoice_agent import InvoiceAgent

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/call/start")
async def start_call(to_number: str, client_name: str):
    script_prompt = f"Generate a 1-sentence greeting for {client_name} about an overdue invoice."
    script = llm_router.invoke(
        prompt=script_prompt,
        mode="generation",
        agent_name="main_api"
    )

    approval = await hitl_manager.wait_for_human(
        checkpoint_type="call_approval", 
        context={"client": client_name, "script": script},
        reason=f"Manual API call trigger requested for {client_name}. Review script before dialing."
    )

    if not approval or not approval.get("approved"):
        return {"status": "cancelled"}

    base_url = os.getenv("BASE_URL")
    
    # UPDATE: Pass client_name safely to Twilio so Twilio sends it back to us
    safe_client = quote(client_name)
    twiml_url = f"{base_url}/call/twiml-initial?client_name={safe_client}"
    
    call_sid = twilio_tool.make_call(to_number, twiml_url)

    return {"status": "calling", "call_sid": call_sid}

# UPDATE: Accept client_name from Twilio
@app.post("/call/twiml-initial")
async def twiml_initial(client_name: str = ""):
    domain = os.getenv("BASE_URL").replace("https://", "").replace("http://", "")
    safe_client = quote(client_name)
    
    # UPDATE: Pass client_name to the WebSocket URL
    response_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="wss://{domain}/twilio-stream?client_name={safe_client}" />
    </Connect>
</Response>"""
    return Response(content=response_xml, media_type="application/xml")

# UPDATE: Accept client_name in the WebSocket
@app.websocket("/twilio-stream")
async def websocket_endpoint(websocket: WebSocket, client_name: str = ""):
    await websocket.accept()

    # --- FETCH LIVE DATA FROM DATABASE ---
    inv_agent = InvoiceAgent()
    client_data = inv_agent.get_client_data(client_name)

    # Build the prompt dynamically
    if client_data:
        total_due = client_data['total_due']
        days_overdue = client_data['max_days_overdue']
        contact = client_data['contact_info']['name'] or "Sir/Madam"
        
        system_prompt = (
            f"You are DebtPilot, an AI payment assistant calling from an Indian firm. "
            f"You are currently on a phone call with {contact} representing {client_name}. "
            f"They have an overdue balance of ₹{total_due}, which is {days_overdue} days late. "
            f"Your goal is to politely inform them of the overdue amount and ask when the payment can be expected. "
            f"Keep your responses extremely short, conversational, and natural. Pause to let them speak. "
            f"Do NOT say 'How can I help you' because you are the one making the call."
        )
        greeting = f"Hello, am I speaking with {contact} from {client_name}?"
    else:
        system_prompt = "You are a professional voice assistant on a phone call. Keep responses short."
        greeting = "Hello, how can I help you today?"

    # Inject the knowledge directly into the agent
    agent = DeepgramVoiceAgent(
        twilio_ws=websocket,
        system_prompt=system_prompt,
        greeting=greeting
    )

    # Run Deepgram Voice Agent in background
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