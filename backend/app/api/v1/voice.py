from fastapi import APIRouter, Request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
from datetime import datetime

router = APIRouter()

@router.post("/incoming/{business_id}")
async def handle_incoming_call(business_id: str, request: Request):
    """Twilio webook for incoming calls
    This is called when someone calls the business phone number"""
    
    #Parse twilio webhook data
    form = await request.form()
    caller_phone = form.get("From")
    call_id = form.get("CallSid")
    print(f"""
    ═══════════════════════════════════════
    📞 INCOMING CALL
    ═══════════════════════════════════════
    Business ID: {business_id}
    Caller: {caller_phone}
    Call SID: {call_sid}
    Time: {datetime.now().strftime('%H:%M:%S')}
    ═══════════════════════════════════════
    """)

    #Create Twilm response
    response = VoiceResponse()
    #Greeting(Australian accent)
    response.say("G'day! Thanks for calling. This is your AI receptionist speaking. "
        "I'm currently in test mode. How can I help you today?",
        voice='Polly.Nicole',  # Australian female voice
        language='en-AU' )
     # Gather speech input
    gather = Gather(
        input='speech',
        action=f'/voice/process/{business_id}',
        timeout=5,
        speech_timeout='auto'
    )
    gather.say(
        "Please tell me what you need.",
        voice='Polly.Nicole',
        language='en-AU'
    )
    response.append(gather)
    
    # If no input, say goodbye
    response.say(
        "Sorry, I didn't hear anything. Please call back. Goodbye!",
        voice='Polly.Nicole',
        language='en-AU'
    )
    
    # Return TwiML XML
    return Response(
        content=str(response),
        media_type="application/xml"
    )

@router.post("/process/{business_id}")
async def process_speech(business_id: str, request: Request):
    """
    Process what the caller said
    """
    form = await request.form()
    speech_result = form.get("SpeechResult")
    
    print(f"""
    ═══════════════════════════════════════
    🎤 CALLER SAID:
    "{speech_result}"
    ═══════════════════════════════════════
    """)
    
    # For now, just repeat what they said
    response = VoiceResponse()
    response.say(
        f"You said: {speech_result}. This is a test. Thank you for calling! Goodbye.",
        voice='Polly.Nicole',
        language='en-AU'
    )
    
    return Response(
        content=str(response),
        media_type="application/xml"
    )