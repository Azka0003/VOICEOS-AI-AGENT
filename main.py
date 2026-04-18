import os
import json
import base64
import asyncio
from fastapi import FastAPI, WebSocket, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from tools.twilio_tool import twilio_tool
from tools.deepgram_tool import DeepgramVoiceAgent
from tools.hitl_tool import hitl_manager
from langchain_groq import ChatGroq

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Groq is still used for non-call tasks (e.g. script generation)
llm = ChatGroq(temperature=0.1, model_name="llama-3.3-70b-versatile")


@app.get("/call/start")
async def start_call(to_number: str, client_name: str):
    # 1. Generate Script
    script_prompt = f"Generate a 1-sentence greeting for {client_name} about an overdue invoice."
    script = llm.invoke(script_prompt).content

    # 2. HITL Checkpoint
    approval = await hitl_manager.wait_for_human(
        "call_approval", {"client": client_name, "script": script}
    )

    if not approval.get("approved"):
        return {"status": "cancelled"}

    # 3. Place Call
    base_url = os.getenv("BASE_URL")
    twiml_url = f"{base_url}/call/twiml-initial"
    call_sid = twilio_tool.make_call(to_number, twiml_url)

    return {"status": "calling", "call_sid": call_sid}


@app.post("/call/twiml-initial")
async def twiml_initial():
    domain = os.getenv("BASE_URL").replace("https://", "").replace("http://", "")
    response_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Connect>
            <Stream url="wss://{domain}/twilio-stream" />
        </Connect>
    </Response>"""
    return Response(content=response_xml, media_type="application/xml")


@app.websocket("/twilio-stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    agent = DeepgramVoiceAgent(
        twilio_ws=websocket,
        # Optionally override the system prompt here per-call
        # system_prompt="You are a collections agent for Acme Corp..."
    )

    # Run Deepgram Voice Agent in background
    agent_task = asyncio.create_task(agent.run())

    try:
        while True:
            data = await websocket.receive_text()
            packet = json.loads(data)

            event = packet.get("event")

            if event == "start":
                print(f"[TWILIO] Stream started: {packet['start']['callSid']}")

            elif event == "media":
                # Forward raw mulaw audio to Deepgram Voice Agent
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
