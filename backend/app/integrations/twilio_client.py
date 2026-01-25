from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather
import os
from dotenv import load_dotenv

load_dotenv()

class TwilioClient:
    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.phone_number = os.getenv("TWILIO_PHONE_NUMBER")
        self.client = Client(self.account_sid, self.auth_token)

    def send_sms(self, to: str, message: str, from_: str | None = None):
        """Send an SMS to the specified phone number"""
        from_number = from_ or self.phone_number
        if not from_number:
            raise ValueError("Missing Twilio from number for SMS.")
        message = self.client.messages.create(
            to=to,
            from_=from_number,
            body=message
        )
        return message
#Initialize the client
twilio_client = TwilioClient()
