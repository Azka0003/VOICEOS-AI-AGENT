import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

class TwilioTool:
    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_number = os.getenv("TWILIO_FROM_NUMBER")
        self.client = Client(self.account_sid, self.auth_token)

    def make_call(self, to_number: str, twiml_url: str) -> str:
        try:
            call = self.client.calls.create(
                to=to_number,
                from_=self.from_number,
                url=twiml_url
            )
            return call.sid
        except Exception as e:
            print(f"[TWILIO ERROR]: {e}")
            return None

twilio_tool = TwilioTool()