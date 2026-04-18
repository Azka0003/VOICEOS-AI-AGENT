"""
deepgram_tool.py — Deepgram Voice Agent Bridge

Bridges Twilio's mulaw audio WebSocket ↔ Deepgram Voice Agent WebSocket.

Two capabilities:
  1. LLM-BASED CALL-END DETECTION
     After every assistant turn a fast Groq call classifies whether the
     conversation has genuinely concluded. Replaces brittle keyword matching.

  2. LIVE FUNCTION-CALLING (DATA ACCESS MID-CALL)
     Tools are registered in the Deepgram Settings payload so the LLM can
     call them during the conversation.  When a FunctionCallRequest arrives
     we dispatch to call_tools.py and send back a FunctionCallResponse.

Deepgram V1 function-calling wire format (from official docs):

  SERVER → CLIENT  (FunctionCallRequest)
  {
    "type": "FunctionCallRequest",
    "functions": [
      {
        "id": "func_12345",
        "name": "get_weather",
        "arguments": "{\"location\": \"San Francisco\"}",
        "client_side": true
      }
    ]
  }

  CLIENT → SERVER  (FunctionCallResponse)
  {
    "type": "FunctionCallResponse",
    "id": "func_12345",
    "name": "get_weather",
    "content": "{\"temperature\": 72}"
  }
"""

import os
import json
import asyncio
import base64
import websockets
from fastapi import WebSocket
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_VOICE_AGENT_URL = "wss://agent.deepgram.com/v1/agent/converse"

# ─────────────────────────────────────────────────────────────────────────────
# Import live-data tool definitions and dispatcher
# ─────────────────────────────────────────────────────────────────────────────
try:
    from tools.call_tools import TOOL_DEFINITIONS, dispatch_tool_call
    _TOOLS_AVAILABLE = True
except ImportError:
    TOOL_DEFINITIONS = []
    _TOOLS_AVAILABLE = False
    def dispatch_tool_call(name, params):
        return json.dumps({"error": "call_tools not available"})


# ─────────────────────────────────────────────────────────────────────────────
# LLM-BASED END-OF-CALL DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def _build_end_of_call_prompt(history: list) -> str:
    transcript = "\n".join(
        f"{t['role'].upper()}: {t['content']}"
        for t in history[-10:]
    )
    return (
        "You are a call-end detector for an AI debt-collection phone agent.\n"
        "Analyze the transcript and decide if the call should NOW end.\n\n"
        "End the call if ANY of these are true:\n"
        "- Customer said goodbye, bye, end the call, cancel, hang up, etc.\n"
        "- Customer gave a clear payment commitment with a specific date\n"
        "- Customer firmly refused and the conversation is clearly finished\n"
        "- Agent already said farewell/thank you with no natural continuation\n"
        "- Customer seems to have gone silent / hung up\n\n"
        f"TRANSCRIPT:\n{transcript}\n\n"
        "Respond with ONLY a JSON object:\n"
        "{\"end_call\": true/false, \"reason\": \"one sentence\"}"
    )


async def _should_end_call(history: list) -> tuple:
    """Returns (should_end: bool, reason: str). Fails safe to False."""
    import httpx
    groq_key = os.getenv("GROQ_API_KEY", "").strip().strip('"').strip("'")
    if not groq_key or len(history) < 2:
        return False, "not enough history"

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                json={
                    "model": os.getenv("GROQ_SPEED_MODEL", "llama-3.1-8b-instant"),
                    "messages": [{"role": "user", "content": _build_end_of_call_prompt(history)}],
                    "max_tokens": 60,
                    "temperature": 0.0,
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            # Strip markdown fences if present
            if "```" in raw:
                raw = raw.split("```")[1].lstrip("json").strip()
            parsed = json.loads(raw)
            return bool(parsed.get("end_call", False)), parsed.get("reason", "")
    except Exception as e:
        print(f"[DG AGENT] End-of-call check failed (keeping call alive): {e}")
        return False, f"error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# AGENT SETTINGS CONFIG
# ─────────────────────────────────────────────────────────────────────────────

def get_agent_config(system_prompt=None, greeting=None, enable_tools=True):
    """
    Builds the Deepgram Settings payload.

    Tool definitions for client-side function calling:
    - No 'endpoint' field  (client-side execution, we handle it ourselves)
    - The server will set client_side=true in FunctionCallRequest events
    """
    functions = []
    if enable_tools and TOOL_DEFINITIONS:
        # Strip any 'endpoint' field — client-side tools don't need it
        for tool in TOOL_DEFINITIONS:
            fn = {k: v for k, v in tool.items() if k != "endpoint"}
            functions.append(fn)

    config = {
        "type": "Settings",
        "audio": {
            "input": {"encoding": "mulaw", "sample_rate": 8000},
            "output": {"encoding": "mulaw", "sample_rate": 8000, "container": "none"},
        },
        "agent": {
            "language": "en",
            "listen": {"provider": {"type": "deepgram", "model": "nova-2"}},
            "think": {
                "prompt": (
                    system_prompt
                    or "You are a professional voice assistant on a phone call. "
                       "Keep your responses concise and conversational."
                ),
                "functions": functions,
            },
            "speak": {"provider": {"type": "deepgram", "model": "aura-2-thalia-en"}},
            "greeting": greeting or "Hello! I am your AI assistant. How can I help you today?",
        },
    }

    llm_provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if llm_provider == "ollama":
        config["agent"]["think"]["provider"] = {
            "type": "open_ai",
            "model": os.getenv("OLLAMA_MODEL", "llama3.2"),
        }
        config["agent"]["think"]["endpoint"] = {
            "url": os.getenv("OLLAMA_URL", "http://localhost:11434/v1/chat/completions"),
        }
    else:
        config["agent"]["think"]["provider"] = {
            "type": "groq",
            "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        }
        config["agent"]["think"]["endpoint"] = {
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "headers": {"Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}"},
        }

    return config


# ─────────────────────────────────────────────────────────────────────────────
# VOICE AGENT
# ─────────────────────────────────────────────────────────────────────────────

class DeepgramVoiceAgent:
    """
    Bridges Twilio mulaw WebSocket <-> Deepgram Voice Agent WebSocket.
    Enhanced with LLM-based call-end detection + live function-calling.
    """

    def __init__(self, twilio_ws: WebSocket, system_prompt=None, greeting=None, enable_tools=True):
        self.twilio_ws = twilio_ws
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        self.dg_ws = None
        self._audio_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self.stream_sid = None
        self.enable_tools = enable_tools
        # Conversation history for end-of-call LLM detection
        self._history: list[dict] = []
        self._config = get_agent_config(system_prompt, greeting, enable_tools)

    def set_stream_sid(self, sid: str):
        self.stream_sid = sid

    def send_audio(self, audio_bytes: bytes):
        if self._running:
            self._audio_queue.put_nowait(audio_bytes)

    async def stop(self):
        self._running = False
        if self.dg_ws:
            try:
                await self.dg_ws.close()
            except Exception:
                pass

    async def run(self):
        if not self.api_key:
            print("\n[FATAL ERROR] Deepgram API key missing. Check .env file.")
            return

        clean_key = self.api_key.replace('"', '').replace("'", "").strip()
        headers = {"Authorization": f"Token {clean_key}"}

        tool_count = len(self._config["agent"]["think"].get("functions", []))
        print(f"\n[DEBUG] Connecting to: {DEEPGRAM_VOICE_AGENT_URL}")
        print(f"[DEBUG] Using API Key starting with: {clean_key[:6]}...")
        print(f"[DEBUG] Live data tools: {'ENABLED' if self.enable_tools else 'DISABLED'} ({tool_count} registered)")

        try:
            async with websockets.connect(
                DEEPGRAM_VOICE_AGENT_URL, additional_headers=headers
            ) as dg_ws:
                self.dg_ws = dg_ws
                self._running = True
                await dg_ws.send(json.dumps(self._config))
                print("[DG AGENT] Settings sent successfully!")
                await asyncio.gather(
                    self._send_audio_loop(dg_ws),
                    self._receive_loop(dg_ws),
                )
        except Exception as e:
            print(f"\n[DG AGENT FATAL ERROR] Could not connect to Deepgram!\nDetails: {e}")

    # ── Internal loops ────────────────────────────────────────────────────────

    async def _send_audio_loop(self, dg_ws):
        while self._running:
            try:
                chunk = await asyncio.wait_for(self._audio_queue.get(), timeout=1.0)
                await dg_ws.send(chunk)
            except asyncio.TimeoutError:
                continue
            except websockets.ConnectionClosed:
                break

    async def _receive_loop(self, dg_ws):
        async for message in dg_ws:
            if isinstance(message, bytes):
                await self._forward_audio_to_twilio(message)
            else:
                await self._handle_event(json.loads(message))

    async def _forward_audio_to_twilio(self, audio_bytes: bytes):
        if not self.stream_sid:
            return
        payload = base64.b64encode(audio_bytes).decode("utf-8")
        try:
            await self.twilio_ws.send_text(json.dumps({
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {"payload": payload},
            }))
        except Exception as e:
            print(f"[DG AGENT] Error forwarding audio to Twilio: {e}")

    # ── Event router ──────────────────────────────────────────────────────────

    async def _handle_event(self, event: dict):
        event_type = event.get("type", "unknown")

        if event_type == "UserStartedSpeaking":
            print("[DG AGENT] User started speaking (barge-in detected)")
            await self._send_twilio_clear()

        elif event_type == "ConversationText":
            role = event.get("role", "?").lower()
            content = event.get("content", "")
            print(f"[DG AGENT] {role.upper()}: {content}")

            if role in ("user", "assistant") and content.strip():
                self._history.append({"role": role, "content": content})

            # After ASSISTANT speaks → check if call should end
            if role == "assistant" and len(self._history) >= 2:
                should_end, reason = await _should_end_call(self._history)
                if should_end:
                    print(f"[DG AGENT] End-of-call detected: {reason}")
                    await asyncio.sleep(1.8)   # let TTS audio finish playing
                    await self._send_twilio_hangup()
                    self._running = False

        elif event_type == "FunctionCallRequest":
            # ── LIVE DATA QUERY ───────────────────────────────────────────────
            # event["functions"] is a LIST — iterate all pending calls
            await self._handle_function_calls(event)

        elif event_type == "AgentAudioDone":
            pass  # end-of-call is handled via ConversationText

        elif event_type == "AgentThinking":
            content = event.get("content", "")
            if content:
                print(f"[DG AGENT] Thinking: {content}")

        elif event_type == "Error":
            print(f"[DG AGENT] Error: {event}")

        # else: SettingsApplied, Welcome, etc. — silently ignore

    # ── Function-calling handler ──────────────────────────────────────────────

    async def _handle_function_calls(self, event: dict):
        """
        Handles FunctionCallRequest from Deepgram.

        The event contains a "functions" list. For each entry where
        client_side is True we execute the function and send back a
        FunctionCallResponse with fields: type, id, name, content.
        """
        functions = event.get("functions", [])
        if not functions:
            print("[DG AGENT] FunctionCallRequest received but 'functions' list is empty.")
            return

        for fn in functions:
            fn_id   = fn.get("id", "")
            fn_name = fn.get("name", "")
            fn_args = fn.get("arguments", "{}")
            client_side = fn.get("client_side", True)

            if not client_side:
                # Server handles it internally — nothing for us to do
                print(f"[DG AGENT] Server-side function '{fn_name}' — skipping client execution.")
                continue

            # Parse arguments
            if isinstance(fn_args, str):
                try:
                    parameters = json.loads(fn_args)
                except json.JSONDecodeError:
                    parameters = {}
            else:
                parameters = fn_args or {}

            print(f"[DG AGENT] 🔧 Tool call: {fn_name}({parameters})")

            # Dispatch to Python implementation
            content = dispatch_tool_call(fn_name, parameters)

            # Send FunctionCallResponse — EXACT V1 schema
            response_msg = {
                "type": "FunctionCallResponse",
                "id": fn_id,
                "name": fn_name,
                "content": content,   # must be a string (JSON-encoded)
            }

            try:
                if self.dg_ws:
                    await self.dg_ws.send(json.dumps(response_msg))
                    print(f"[DG AGENT] ✓ Tool result sent: {fn_name} → {content[:120]}...")
            except Exception as e:
                print(f"[DG AGENT] Failed to send tool result for '{fn_name}': {e}")

    # ── Twilio control ────────────────────────────────────────────────────────

    async def _send_twilio_clear(self):
        if not self.stream_sid:
            return
        try:
            await self.twilio_ws.send_text(json.dumps({
                "event": "clear",
                "streamSid": self.stream_sid,
            }))
        except Exception:
            pass

    async def _send_twilio_hangup(self):
        if not self.stream_sid:
            return
        try:
            await self.twilio_ws.send_text(json.dumps({
                "event": "stop",
                "streamSid": self.stream_sid,
            }))
            print("[DG AGENT] Hangup signal sent to Twilio.")
        except Exception as e:
            print(f"[DG AGENT] Error sending hangup: {e}")