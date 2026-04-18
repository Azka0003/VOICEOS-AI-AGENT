"""
deepgram_tool.py — Deepgram Voice Agent Bridge

Bridges Twilio mulaw WebSocket ↔ Deepgram Voice Agent WebSocket.

Fixes in this version:
  1. Hangup dedup — _hangup_initiated flag ensures it fires exactly once
  2. Twilio REST hangup — calls twilio_tool.end_call(call_sid) for a real hang-up
  3. Call outcome extraction — fires a POST to /call/outcome when call ends
  4. LLM-based end-of-call detection (replaces keyword matching)
  5. Live function-calling for data access mid-call
"""

import os, json, asyncio, base64
import websockets
import httpx
from fastapi import WebSocket
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_VOICE_AGENT_URL = "wss://agent.deepgram.com/v1/agent/converse"

try:
    from tools.call_tools import TOOL_DEFINITIONS, dispatch_tool_call
    _TOOLS_AVAILABLE = True
except ImportError:
    TOOL_DEFINITIONS = []
    _TOOLS_AVAILABLE = False
    def dispatch_tool_call(name, params):
        return json.dumps({"error": "call_tools not available"})

# ─────────────────────────────────────────────────────────────────────────────
# LLM end-of-call detection
# ─────────────────────────────────────────────────────────────────────────────

def _eoc_prompt(history: list) -> str:
    transcript = "\n".join(f"{t['role'].upper()}: {t['content']}" for t in history[-10:])
    return (
        "You are a call-end detector for an AI debt-collection phone agent.\n"
        "Decide if the call should end NOW based on the transcript.\n\n"
        "End if ANY are true:\n"
        "- Customer said goodbye/bye/hang up/cancel/end the call/thank you (and conversation is done)\n"
        "- Customer gave a firm payment commitment with a specific date\n"
        "- Customer clearly refused and conversation is over\n"
        "- Agent said farewell and there is nothing left to discuss\n\n"
        f"TRANSCRIPT:\n{transcript}\n\n"
        "Reply ONLY with JSON: {\"end_call\": true/false, \"reason\": \"one sentence\"}"
    )

async def _should_end_call(history: list) -> tuple:
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
                    "messages": [{"role": "user", "content": _eoc_prompt(history)}],
                    "max_tokens": 60, "temperature": 0.0,
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            if "```" in raw:
                raw = raw.split("```")[1].lstrip("json").strip()
            parsed = json.loads(raw)
            return bool(parsed.get("end_call", False)), parsed.get("reason", "")
    except Exception as e:
        print(f"[DG AGENT] EOC check failed (keeping call): {e}")
        return False, f"error: {e}"

# ─────────────────────────────────────────────────────────────────────────────
# Settings config
# ─────────────────────────────────────────────────────────────────────────────

def get_agent_config(system_prompt=None, greeting=None, enable_tools=True):
    functions = []
    if enable_tools and TOOL_DEFINITIONS:
        functions = [{k: v for k, v in t.items() if k != "endpoint"} for t in TOOL_DEFINITIONS]

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
                "prompt": system_prompt or "You are a professional voice assistant. Keep responses concise.",
                "functions": functions,
            },
            "speak": {"provider": {"type": "deepgram", "model": "aura-2-thalia-en"}},
            "greeting": greeting or "Hello! How can I help you today?",
        },
    }

    llm_provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if llm_provider == "ollama":
        config["agent"]["think"]["provider"] = {"type": "open_ai", "model": os.getenv("OLLAMA_MODEL", "llama3.2")}
        config["agent"]["think"]["endpoint"] = {"url": os.getenv("OLLAMA_URL", "http://localhost:11434/v1/chat/completions")}
    else:
        config["agent"]["think"]["provider"] = {"type": "groq", "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")}
        config["agent"]["think"]["endpoint"] = {
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "headers": {"Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}"},
        }
    return config

# ─────────────────────────────────────────────────────────────────────────────
# Voice Agent
# ─────────────────────────────────────────────────────────────────────────────

class DeepgramVoiceAgent:
    def __init__(self, twilio_ws: WebSocket, system_prompt=None, greeting=None,
                 enable_tools=True, call_sid: str = None, client_name: str = None,
                 event_broadcast=None):
        self.twilio_ws = twilio_ws
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        self.dg_ws = None
        self._audio_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self.stream_sid = None
        self.call_sid = call_sid          # Twilio call SID for REST hangup
        self.client_name = client_name    # For outcome reporting
        self.event_broadcast = event_broadcast  # async fn(event_dict) for SSE

        # ── State ─────────────────────────────────────────────────────────────
        self._history: list = []
        self._hangup_initiated = False    # Dedup: fire hangup exactly once
        self._call_outcome = "no_response"
        self._payment_commitment = None
        self._call_notes = []

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
            print("\n[FATAL] Deepgram API key missing.")
            return
        clean_key = self.api_key.replace('"','').replace("'",'').strip()
        headers = {"Authorization": f"Token {clean_key}"}
        tool_count = len(self._config["agent"]["think"].get("functions", []))
        print(f"[DEBUG] Connecting to Deepgram. Tools: {tool_count} registered.")
        try:
            async with websockets.connect(DEEPGRAM_VOICE_AGENT_URL, additional_headers=headers) as dg_ws:
                self.dg_ws = dg_ws
                self._running = True
                await dg_ws.send(json.dumps(self._config))
                print("[DG AGENT] Settings sent.")
                await asyncio.gather(self._send_audio_loop(dg_ws), self._receive_loop(dg_ws))
        except Exception as e:
            print(f"[DG AGENT FATAL] {e}")
        finally:
            await self._finalize_call()

    async def _finalize_call(self):
        """Called when call ends — posts outcome to backend for Excel write-back."""
        if not self.client_name:
            return
        base_url = os.getenv("BASE_URL", "http://localhost:8000")
        payload = {
            "client_name": self.client_name,
            "call_outcome": self._call_outcome,
            "payment_commitment": self._payment_commitment,
            "notes": " | ".join(self._call_notes)
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(f"{base_url}/call/outcome", json=payload)
            print(f"[DG AGENT] Outcome posted: {self._call_outcome} for {self.client_name}")
        except Exception as e:
            print(f"[DG AGENT] Could not post outcome: {e}")

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
                await self._forward_audio(message)
            else:
                await self._handle_event(json.loads(message))

    async def _forward_audio(self, audio_bytes: bytes):
        if not self.stream_sid:
            return
        try:
            await self.twilio_ws.send_text(json.dumps({
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {"payload": base64.b64encode(audio_bytes).decode()},
            }))
        except Exception:
            pass

    async def _handle_event(self, event: dict):
        etype = event.get("type", "")

        if etype == "UserStartedSpeaking":
            print("[DG AGENT] User speaking (barge-in)")
            await self._send_clear()

        elif etype == "ConversationText":
            role = event.get("role", "").lower()
            content = event.get("content", "")
            print(f"[DG AGENT] {role.upper()}: {content}")

            if role in ("user", "assistant") and content.strip():
                self._history.append({"role": role, "content": content})
                # Broadcast to SSE stream for live transcript
                if self.event_broadcast:
                    await self.event_broadcast({
                        "type": "transcript",
                        "role": role,
                        "content": content,
                        "client": self.client_name
                    })

            # Extract call outcome signals from user turns
            if role == "user":
                lower = content.lower()
                if any(w in lower for w in ["yes", "okay", "fine", "will pay", "friday", "monday", "tuesday", "wednesday", "thursday", "week"]):
                    self._call_outcome = "confirmed"

            # End-of-call check after EVERY assistant turn — but only act once
            if role == "assistant" and len(self._history) >= 2 and not self._hangup_initiated:
                should_end, reason = await _should_end_call(self._history)
                if should_end:
                    self._hangup_initiated = True   # ← dedup flag set HERE
                    print(f"[DG AGENT] End-of-call: {reason}")
                    await asyncio.sleep(1.8)
                    await self._hangup()

        elif etype == "FunctionCallRequest":
            await self._handle_function_calls(event)

        elif etype == "Error":
            print(f"[DG AGENT] Error: {event}")

    async def _handle_function_calls(self, event: dict):
        for fn in event.get("functions", []):
            fn_id   = fn.get("id", "")
            fn_name = fn.get("name", "")
            fn_args = fn.get("arguments", "{}")
            if not fn.get("client_side", True):
                continue
            try:
                parameters = json.loads(fn_args) if isinstance(fn_args, str) else (fn_args or {})
            except json.JSONDecodeError:
                parameters = {}
            print(f"[DG AGENT] 🔧 {fn_name}({parameters})")

            # Track payment promises from tool calls
            if fn_name == "record_payment_promise":
                self._call_outcome = "confirmed"
                self._payment_commitment = parameters.get("promise_date")
                self._call_notes.append(f"Promise: {parameters.get('amount','full')} by {parameters.get('promise_date')}")

            content = dispatch_tool_call(fn_name, parameters)
            try:
                if self.dg_ws:
                    await self.dg_ws.send(json.dumps({
                        "type": "FunctionCallResponse",
                        "id": fn_id, "name": fn_name, "content": content,
                    }))
                    print(f"[DG AGENT] ✓ {fn_name} → sent")
            except Exception as e:
                print(f"[DG AGENT] Failed sending tool result: {e}")

    async def _hangup(self):
        """Two-step hangup: Twilio REST (real hangup) + stream stop signal."""
        # Step 1: REST API — actually ends the phone call
        if self.call_sid:
            from tools.twilio_tool import twilio_tool
            twilio_tool.end_call(self.call_sid)

        # Step 2: Close the media stream WebSocket
        if self.stream_sid:
            try:
                await self.twilio_ws.send_text(json.dumps({
                    "event": "stop", "streamSid": self.stream_sid,
                }))
            except Exception:
                pass

        self._running = False

    async def _send_clear(self):
        if not self.stream_sid:
            return
        try:
            await self.twilio_ws.send_text(json.dumps({"event": "clear", "streamSid": self.stream_sid}))
        except Exception:
            pass
