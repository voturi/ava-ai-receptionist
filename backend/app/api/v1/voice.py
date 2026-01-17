from fastapi import APIRouter, Request, Response
from twilio.twiml.voice_response import VoiceResponse, Gather
from datetime import datetime
from app.services.ai_service import ai_service
import json

router = APIRouter()

# In-memory storage for conversations (temporary - we'll use database later)
conversations = {}

@router.post("/incoming/{business_id}")
async def handle_incoming_call(business_id: str, request: Request):
    """
    Twilio webhook for incoming calls
    """
    form = await request.form()
    caller_phone = form.get("From")
    call_sid = form.get("CallSid")
    
    print(f"""
    ═══════════════════════════════════════
    📞 NEW CALL
    ═══════════════════════════════════════
    Business: {business_id}
    Caller: {caller_phone}
    Call SID: {call_sid}
    Time: {datetime.now().strftime('%H:%M:%S')}
    ═══════════════════════════════════════
    """)
    
    # Initialize conversation history
    conversations[call_sid] = {
        "history": [],
        "collected_data": {},
        "business_id": business_id,
        "caller_phone": caller_phone
    }
    
    # Get AI greeting
    ai_response = await ai_service.get_response(
        user_message="[CALL STARTED - Greet the customer]",
        conversation_history=[],
        business_name="Bondi Hair Salon"  # We'll make this dynamic later
    )
    
    # Save AI response to history
    conversations[call_sid]["history"].append({
        "role": "assistant",
        "content": ai_response["text"]
    })
    
    # Create TwiML response
    response = VoiceResponse()
    
    # AI greeting
    response.say(
        ai_response["text"],
        voice='Polly.Nicole',
        language='en-AU'
    )
    
    # Gather user input
    gather = Gather(
        input='speech',
        action=f'/voice/process/{business_id}/{call_sid}',
        timeout=5,
        speech_timeout='auto',
        language='en-AU'
    )
    gather.say(
        "I'm listening.",
        voice='Polly.Nicole',
        language='en-AU'
    )
    response.append(gather)
    
    # Fallback if no response
    response.say(
        "Sorry, I didn't hear you. Please call back. Goodbye!",
        voice='Polly.Nicole',
        language='en-AU'
    )
    
    return Response(content=str(response), media_type="application/xml")


@router.post("/process/{business_id}/{call_sid}")
async def process_speech(business_id: str, call_sid: str, request: Request):
    """
    Process user speech and continue conversation
    """
    form = await request.form()
    speech_result = form.get("SpeechResult", "")
    
    # Get conversation
    conversation = conversations.get(call_sid, {
        "history": [],
        "collected_data": {},
        "business_id": business_id
    })
    
    print(f"""
    ═══════════════════════════════════════
    🎤 CUSTOMER SAID:
    "{speech_result}"
    ═══════════════════════════════════════
    """)
    
    # Add user message to history
    conversation["history"].append({
        "role": "user",
        "content": speech_result
    })
    
    # Get AI response
    ai_response = await ai_service.get_response(
        user_message=speech_result,
        conversation_history=conversation["history"],
        business_name="Bondi Hair Salon"
    )
    
    print(f"""
    ═══════════════════════════════════════
    🤖 AI RESPONDS:
    "{ai_response['text']}"
    
    Intent: {ai_response['intent']}
    Collected: {json.dumps(ai_response['collected_data'], indent=2)}
    ═══════════════════════════════════════
    """)
    
    # Add AI response to history
    conversation["history"].append({
        "role": "assistant",
        "content": ai_response["text"]
    })
    
    # Update collected data
    conversation["collected_data"].update(ai_response["collected_data"])
    
    # Save conversation
    conversations[call_sid] = conversation
    
    # Build TwiML response
    response = VoiceResponse()
    
    # Check if should transfer
    if ai_response.get("should_transfer"):
        response.say(
            ai_response["text"],
            voice='Polly.Nicole',
            language='en-AU'
        )
        # For now, just end call (we'll add real transfer later)
        response.say(
            "Thank you for calling. Goodbye!",
            voice='Polly.Nicole',
            language='en-AU'
        )
        return Response(content=str(response), media_type="application/xml")
    
    # Continue conversation
    response.say(
        ai_response["text"],
        voice='Polly.Nicole',
        language='en-AU'
    )
    
    # Check if booking seems complete
    if _is_booking_complete(conversation["collected_data"], conversation["history"]):
        # Booking complete!
        response.say(
            "Perfect! Your appointment is confirmed. You'll receive an SMS confirmation shortly. Thank you for calling! Goodbye!",
            voice='Polly.Nicole',
            language='en-AU'
        )
        
        print(f"""
        ═══════════════════════════════════════
        ✅ BOOKING COMPLETE!
        ═══════════════════════════════════════
        Data: {json.dumps(conversation['collected_data'], indent=2)}
        ═══════════════════════════════════════
        """)
        
        # Clean up conversation
        del conversations[call_sid]
        
    else:
        # Continue gathering information
        gather = Gather(
            input='speech',
            action=f'/voice/process/{business_id}/{call_sid}',
            timeout=5,
            speech_timeout='auto',
            language='en-AU'
        )
        response.append(gather)
        
        # Timeout fallback
        response.say(
            "Are you still there? Please call back if you need anything. Goodbye!",
            voice='Polly.Nicole',
            language='en-AU'
        )
    
    return Response(content=str(response), media_type="application/xml")


def _is_booking_complete(collected_data: dict, history: list) -> bool:
    """
    Simple check if we have enough info for a booking
    (We'll improve this logic later)
    """
    # Check if conversation mentions "confirm" or "perfect"
    last_messages = " ".join([msg.get("content", "") for msg in history[-3:]])
    
    if "confirm" in last_messages.lower() or "perfect" in last_messages.lower():
        # Check if we have basic info
        has_service = "service" in collected_data or any(
            word in last_messages.lower() 
            for word in ["haircut", "color", "balayage"]
        )
        return has_service
    
    return False


@router.get("/conversations")
async def get_active_conversations():
    """
    Debug endpoint to see active conversations
    """
    return {
        "active_conversations": len(conversations),
        "conversations": conversations
    }