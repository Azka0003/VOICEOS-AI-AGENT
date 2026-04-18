import os
import json
import asyncio
import base64
import websockets
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_VOICE_AGENT_URL = "wss://agent.deepgram.com/v1/agent/converse"

def get_agent_config(system_prompt: str | None = None):
    config = {
        "type": "Settings",
        "audio": {
            "input": {
                "encoding": "mulaw",
                "sample_rate": 8000,
            },
            "output": {
                "encoding": "mulaw",
                "sample_rate": 8000,
                "container": "none",
            },
        },
        "agent": {
            "language": "en",
            "listen": {
                "provider": {
                    "type": "deepgram",
                    "model": "nova-2",
                }
            },
            "think": {
                "prompt": system_prompt or "You are a helpful AI assistant...",
            },
            "speak": {
                "provider": {
                    "type": "deepgram",
                    "model": "aura-2-thalia-en",
                }
            },
            "greeting": "Hello! I am your AI assistant. How can I help you today?",
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
            "headers": {
                "Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}"
            }
        }

    return config


class DeepgramVoiceAgent:
    """
    Bridges Twilio's mulaw audio WebSocket <-> Deepgram Voice Agent WebSocket.
    """

    def __init__(self, twilio_ws, system_prompt: str | None = None):
        self.twilio_ws = twilio_ws
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        self.dg_ws = None
        self._audio_queue: asyncio.Queue = asyncio.Queue()
        self._running = False

        # Generate config based on env vars + system prompt
        self._config = get_agent_config(system_prompt)

    def send_audio(self, audio_bytes: bytes):
        """Queue raw mulaw audio bytes received from Twilio."""
        if self._running:
            self._audio_queue.put_nowait(audio_bytes)

    async def stop(self):
        self._running = False
        if self.dg_ws:
            await self.dg_ws.close()

    async def run(self):
        if not self.api_key:
            print("\n[FATAL ERROR] Deepgram API key is completely missing! Check your .env file.")
            return

        # Automatically fix accidental quotes or spaces from the .env file
        clean_key = self.api_key.replace('"', '').replace("'", "").strip()
        headers = {"Authorization": f"Token {clean_key}"}
        
        print(f"\n[DEBUG] Connecting to: {DEEPGRAM_VOICE_AGENT_URL}")
        print(f"[DEBUG] Using API Key starting with: {clean_key[:6]}...")

        try:
            async with websockets.connect(
                DEEPGRAM_VOICE_AGENT_URL, additional_headers=headers
            ) as dg_ws:
                self.dg_ws = dg_ws
                self._running = True

                # Send settings first
                await dg_ws.send(json.dumps(self._config))
                print("[DG AGENT] Settings sent successfully!")

                # Run sender + receiver concurrently
                await asyncio.gather(
                    self._send_audio_loop(dg_ws),
                    self._receive_loop(dg_ws),
                )
        except Exception as e:
            print(f"\n[DG AGENT FATAL ERROR] Could not connect to Deepgram!")
            print(f"Error Details: {e}")

    async def _send_audio_loop(self, dg_ws):
        """Forward mulaw audio from Twilio → Deepgram."""
        while self._running:
            try:
                chunk = await asyncio.wait_for(self._audio_queue.get(), timeout=1.0)
                await dg_ws.send(chunk)
            except asyncio.TimeoutError:
                continue
            except websockets.ConnectionClosed:
                break

    async def _receive_loop(self, dg_ws):
        """Receive audio/events from Deepgram and forward audio → Twilio."""
        async for message in dg_ws:
            if isinstance(message, bytes):
                # Audio output from Deepgram TTS — forward to Twilio as-is
                await self._forward_audio_to_twilio(message)
            else:
                # JSON event (transcript, agent thinking, errors, etc.)
                await self._handle_event(json.loads(message))

    async def _forward_audio_to_twilio(self, audio_bytes: bytes):
        """Send TTS audio back to Twilio over its media WebSocket."""
        payload = base64.b64encode(audio_bytes).decode("utf-8")
        media_msg = {
            "event": "media",
            "media": {"payload": payload},
        }
        try:
            await self.twilio_ws.send_text(json.dumps(media_msg))
        except Exception as e:
            print(f"[DG AGENT] Error forwarding audio to Twilio: {e}")

    async def _handle_event(self, event: dict):
        event_type = event.get("type", "unknown")

        if event_type == "UserStartedSpeaking":
            print("[DG AGENT] User started speaking (barge-in detected)")
            await self._send_twilio_clear()

        elif event_type == "ConversationText":
            role = event.get("role", "?")
            content = event.get("content", "")
            print(f"[DG AGENT] {role.upper()}: {content}")

        elif event_type == "AgentThinking":
            print(f"[DG AGENT] Thinking: {event.get('content', '')}")

        elif event_type == "Error":
            print(f"[DG AGENT] Error: {event}")

    async def _send_twilio_clear(self):
        """Tell Twilio to discard any buffered audio (barge-in support)."""
        clear_msg = {"event": "clear"}
        try:
            await self.twilio_ws.send_text(json.dumps(clear_msg))
        except Exception:
            pass