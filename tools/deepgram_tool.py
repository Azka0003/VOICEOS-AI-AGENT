import os
import json
import asyncio
import base64
import websockets
from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_VOICE_AGENT_URL = "wss://agent.deepgram.com/v1/agent/converse"

def get_agent_config(system_prompt: str | None = None):
    """
    Generates the configuration for the Deepgram Voice Agent.
    Includes logic for selecting LLM provider (Groq or Ollama).
    """
    # --- FIX: Update system_prompt to be more specific for voice agents ---
    # This prompt tells the AI it's on a phone call and can hear.
    default_system_prompt = (
        "You are a helpful AI assistant for a company. "
        "You are speaking to a user on the phone. "
        "You can hear them perfectly and should respond conversationally and concisely. "
        "Assume you are calling about an overdue invoice if appropriate. "
        "If you don't know who you are, introduce yourself as an AI assistant for the company."
    )
    final_system_prompt = system_prompt or default_system_prompt

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
                "container": "none", # No container needed for raw audio
            },
        },
        "agent": {
            "language": "en",
            "listen": {
                "provider": {
                    "type": "deepgram",
                    "model": "nova-2",
                    # Adjust VAD sensitivity if needed, but defaults are usually good.
                    # "options": {
                    #     "vad_threshold": 0.5 # Lower value = more sensitive to speech
                    # }
                }
            },
            "think": {
                "prompt": final_system_prompt, # Use the updated prompt
                "provider": {}, # Will be filled below
                "endpoint": {}, # Will be filled below
            },
            "speak": {
                "provider": {
                    "type": "deepgram",
                    "model": "aura-2-thalia-en", # Or another suitable Aura model
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
    else: # Default to Groq
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
    Handles sending audio to Deepgram and receiving/forwarding responses.
    """

    def __init__(self, twilio_ws: websockets.WebSocket, system_prompt: str | None = None):
        self.twilio_ws = twilio_ws
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        self.dg_ws: websockets.WebSocketClientProtocol | None = None # Type hint
        self._audio_queue: asyncio.Queue = asyncio.Queue()
        self._running: bool = False
        self.stream_sid: str | None = None # --- FIX: Add to store streamSid ---

        # Generate config based on env vars + system prompt
        self._config = get_agent_config(system_prompt)

    def set_stream_sid(self, sid: str):
        """ --- FIX: Method to set the stream SID received from Twilio --- """
        self.stream_sid = sid
        print(f"[DG AGENT] Stream SID set to: {self.stream_sid}")

    def send_audio(self, audio_bytes: bytes):
        """Queue raw mulaw audio bytes received from Twilio."""
        if self._running:
            self._audio_queue.put_nowait(audio_bytes)

    async def stop(self):
        """Gracefully stops the agent by closing the Deepgram WebSocket and signaling the queue."""
        self._running = False
        if self.dg_ws:
            await self.dg_ws.close()
            print("[DG AGENT] Deepgram WebSocket closed.")
        # Clear the queue to unblock the sender if it's waiting
        while not self._audio_queue.empty():
            self._audio_queue.get_nowait()
            self._audio_queue.task_done()
        print("[DG AGENT] Audio queue cleared.")


    async def run(self):
        """
        Connects to the Deepgram Voice Agent, sends configuration,
        and starts the loops for sending audio and receiving events.
        """
        if not self.api_key:
            print("\n[FATAL ERROR] Deepgram API key is completely missing! Check your .env file.")
            return

        # Automatically fix accidental quotes or spaces from the .env file
        clean_key = self.api_key.replace('"', '').replace("'", "").strip()
        headers = {"Authorization": f"Token {clean_key}"}

        print(f"\n[DEBUG] Connecting to: {DEEPGRAM_VOICE_AGENT_URL}")
        print(f"[DEBUG] Using API Key starting with: {clean_key[:6]}...")

        try:
            # Use websockets.connect for the Deepgram connection
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
        except websockets.ConnectionClosed as e:
            print(f"\n[DG AGENT] Connection to Deepgram closed unexpectedly: {e.code} - {e.reason}")
        except Exception as e:
            print(f"\n[DG AGENT FATAL ERROR] Could not connect to Deepgram or an error occurred during runtime!")
            print(f"Error Details: {e}")
        finally:
            print("[DG AGENT] Run loop finished.")
            self._running = False # Ensure flag is set if an exception occurs before it's set


    async def _send_audio_loop(self, dg_ws: websockets.WebSocketClientProtocol):
        """Forward mulaw audio from Twilio → Deepgram."""
        print("[DG AGENT] Audio sender loop started.")
        while self._running:
            try:
                # Wait for audio data from the queue
                chunk = await asyncio.wait_for(self._audio_queue.get(), timeout=1.0)
                if chunk:
                    await dg_ws.send(chunk)
                    self._audio_queue.task_done() # Mark task as done
            except asyncio.TimeoutError:
                # No audio data for a while, just continue waiting
                continue
            except websockets.ConnectionClosed:
                print("[DG AGENT] Audio sender loop: Deepgram connection closed.")
                break
            except Exception as e:
                print(f"[DG AGENT] Error in _send_audio_loop: {e}")
                break
        print("[DG AGENT] Audio sender loop stopped.")

    async def _receive_loop(self, dg_ws: websockets.WebSocketClientProtocol):
        """Receive audio/events from Deepgram and forward audio → Twilio."""
        print("[DG AGENT] Receiver loop started.")
        try:
            async for message in dg_ws:
                if isinstance(message, bytes):
                    # Audio output from Deepgram TTS — forward to Twilio as-is
                    await self._forward_audio_to_twilio(message)
                else:
                    # JSON event (transcript, agent thinking, errors, etc.)
                    await self._handle_event(json.loads(message))
        except websockets.ConnectionClosed:
            print("[DG AGENT] Receiver loop: Deepgram connection closed.")
        except Exception as e:
            print(f"[DG AGENT] Error in _receive_loop: {e}")
        finally:
            print("[DG AGENT] Receiver loop stopped.")

    async def _forward_audio_to_twilio(self, audio_bytes: bytes):
        """Send TTS audio back to Twilio over its media WebSocket."""
        if not self.stream_sid:
            # This is a critical error. Without streamSid, Twilio won't know which call this audio belongs to.
            print("[DG AGENT] WARNING: Cannot forward audio, stream_sid is not set!")
            return

        payload = base64.b64encode(audio_bytes).decode("utf-8")
        media_msg = {
            "event": "media",
            # --- FIX: MUST include the streamSid ---
            "streamSid": self.stream_sid,
            "media": {"payload": payload},
        }
        try:
            # Use send_text for JSON messages
            await self.twilio_ws.send_text(json.dumps(media_msg))
            # print(f"[DG AGENT] Forwarded audio chunk with streamSid: {self.stream_sid}") # Optional: for debugging
        except Exception as e:
            print(f"[DG AGENT] Error forwarding audio to Twilio: {e}")

    async def _handle_event(self, event: dict):
        """Processes incoming JSON events from the Deepgram Voice Agent."""
        event_type = event.get("type", "unknown")

        if event_type == "UserStartedSpeaking":
            print("[DG AGENT] User started speaking (barge-in detected)")
            await self._send_twilio_clear() # Tell Twilio to clear buffers

        elif event_type == "ConversationText":
            role = event.get("role", "?")
            content = event.get("content", "")
            print(f"[DG AGENT] {role.upper()}: {content}")

        elif event_type == "AgentThinking":
            print(f"[DG AGENT] Thinking: {event.get('content', '')}")

        elif event_type == "Error":
            print(f"[DG AGENT] Error: {event}")
            # You might want to add more robust error handling here, e.g., stop the call.

    async def _send_twilio_clear(self):
        """
        Tells Twilio to discard any buffered audio that was intended to be sent
        to the user. This is crucial for barge-in support, allowing the agent
        to interrupt its own speech.
        """
        # Note: This message is sent TO Twilio, not FROM Twilio.
        # It's an instruction to Twilio's media stream.
        clear_msg = {"event": "clear"}
        try:
            # Use send_text for JSON messages
            await self.twilio_ws.send_text(json.dumps(clear_msg))
            # print("[DG AGENT] Sent 'clear' event to Twilio.") # Optional: for debugging
        except Exception as e:
            print(f"[DG AGENT] Error sending 'clear' event to Twilio: {e}")