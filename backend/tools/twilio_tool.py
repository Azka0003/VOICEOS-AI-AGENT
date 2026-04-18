"""twilio_tool.py — Twilio outbound calling + call control."""
import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

class TwilioTool:
    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token  = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_number = os.getenv("TWILIO_FROM_NUMBER")
        self.client = Client(self.account_sid, self.auth_token)

    def make_call(self, to_number: str, twiml_url: str) -> str | None:
        try:
            call = self.client.calls.create(
                to=to_number,
                from_=self.from_number,
                url=twiml_url
            )
            print(f"[TWILIO] Call placed → {call.sid}")
            return call.sid
        except Exception as e:
            print(f"[TWILIO ERROR] make_call: {e}")
            return None

    def end_call(self, call_sid: str) -> bool:
        """Terminate a live call via Twilio REST API — the only reliable way to hang up."""
        try:
            self.client.calls(call_sid).update(status="completed")
            print(f"[TWILIO] Call ended via REST: {call_sid}")
            return True
        except Exception as e:
            print(f"[TWILIO ERROR] end_call({call_sid}): {e}")
            return False

twilio_tool = TwilioTool()
