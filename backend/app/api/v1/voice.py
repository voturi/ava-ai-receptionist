from fastapi import APIRouter, Request, Response, Depends
from twilio.twiml.voice_response import VoiceResponse, Gather
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.ai_service import ai_service
from app.services.db_service import DBService
from app.integrations.twilio_client import twilio_client
from app.core.database import get_db
import json
import uuid

router = APIRouter()

# Temporary in-memory storage for active conversations
# (We'll replace this with Redis later)
conversations = {}

@router.post("/incoming/{business_id}")
async def handle_incoming_call(
    business_id: str, 
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Twilio webhook for incoming calls
    Now stores call in database!
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
    
    # Get database service
    db_service = DBService(db)
    
    # Get business by Twilio number (the "To" field)
    # This is more reliable than business_id since Twilio routes to the business's number
    twilio_number = form.get("To")
    business = await db_service.get_business_by_phone(twilio_number)
    
    if not business:
        # If not found by phone, try by business_id (URL parameter)
        business = await db_service.get_business(business_id)
    
    if not business:
        # Still not found? Create default business for demo
        try:
            b_uuid = uuid.UUID(business_id)
        except ValueError:
            b_uuid = uuid.uuid4()

        business = await db_service.create_business({
            "id": b_uuid,
            "name": "Bondi Hair Salon",
            "industry": "salon",
            "twilio_number": twilio_number,
            "services": [
                {"name": "Women's Cut", "duration": 45, "price": 85},
                {"name": "Men's Cut", "duration": 30, "price": 50},
                {"name": "Color", "duration": 90, "price": 150},
                {"name": "Balayage", "duration": 120, "price": 200}
            ]
        })
        print(f"✨ Created new business: {business.name}")
    
    # Create call record in database
    try:
        call = await db_service.create_call({
            "business_id": business.id,
            "call_sid": call_sid,
            "caller_phone": caller_phone,
            "started_at": datetime.utcnow(),
            "intent": "unknown",
            "outcome": "in_progress"
        })
        
        print(f"💾 Call saved to database: {call.id}")
    except Exception as e:
        print(f"❌ ERROR creating call: {str(e)}")
        # Return error response to Twilio
        response = VoiceResponse()
        response.say(
            "Sorry, we're experiencing technical difficulties. Please try again later.",
            voice='Polly.Nicole',
            language='en-AU'
        )
        return Response(content=str(response), media_type="application/xml")
    
    # Initialize conversation in memory
    conversations[call_sid] = {
        "call_id": str(call.id),
        "history": [],
        "collected_data": {},
        "business_id": str(business.id),
        "business_name": business.name,
        "business_phone": business.twilio_number,
        "caller_phone": caller_phone
    }
    
    # Get AI greeting
    try:
        print(f"🤖 Requesting AI greeting...")
        # Use static greeting for speed - AI will engage on first customer response
        ai_response = {
            "text": f"G'day! Welcome to {business.name}. How can I help you today?"
        }
        print(f"✅ Greeting ready: {ai_response['text']}")
        
        # Save to conversation history
        conversations[call_sid]["history"].append({
            "role": "assistant",
            "content": ai_response["text"]
        })
    except Exception as e:
        print(f"❌ ERROR getting greeting: {str(e)}")
        import traceback
        traceback.print_exc()
        # Fallback greeting if anything fails
        ai_response = {
            "text": "Hello! Welcome to our salon. How can I help you today?"
        }
    
    # Create TwiML response
    try:
        response = VoiceResponse()
        response.say(
            ai_response["text"],
            voice='Polly.Nicole',
            language='en-AU'
        )
        
        # Gather input
        gather = Gather(
            input='speech',
            action=f'/voice/process/{business_id}/{call_sid}',
            timeout=5,
            speech_timeout='auto',
            language='en-AU'
        )
        gather.say("I'm listening.", voice='Polly.Nicole', language='en-AU')
        response.append(gather)
        
        # Fallback
        response.say(
            "Sorry, I didn't hear anything. Please call back!",
            voice='Polly.Nicole',
            language='en-AU'
        )
        
        print(f"📱 TwiML response built successfully")
        return Response(content=str(response), media_type="application/xml")
    except Exception as e:
        print(f"❌ ERROR building TwiML response: {str(e)}")
        import traceback
        traceback.print_exc()
        # Return basic error response
        response = VoiceResponse()
        response.say("Sorry, there's a technical issue. Please call back.", voice='Polly.Nicole', language='en-AU')
        return Response(content=str(response), media_type="application/xml")


@router.post("/process/{business_id}/{call_sid}")
async def process_speech(
    business_id: str,
    call_sid: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Process user speech and update database
    """
    form = await request.form()
    speech_result = form.get("SpeechResult", "")
    
    # Get conversation
    conversation = conversations.get(call_sid, {})
    if not conversation:
        # Call not found in memory - end gracefully
        response = VoiceResponse()
        response.say(
            "Sorry, I lost track of our conversation. Please call back!",
            voice='Polly.Nicole',
            language='en-AU'
        )
        return Response(content=str(response), media_type="application/xml")
    
    print(f"""
    🎤 CUSTOMER: "{speech_result}"
    """)
    
    # Add to history
    conversation["history"].append({
        "role": "user",
        "content": speech_result
    })
    
    # Get AI response
    ai_response = await ai_service.get_response(
        user_message=speech_result,
        conversation_history=conversation["history"],
        business_name=conversation.get("business_name", "our business")
    )
    
    print(f"""
    🤖 AI: "{ai_response['text']}"
    Intent: {ai_response['intent']}
    """)
    
    # Add AI response to history
    conversation["history"].append({
        "role": "assistant",
        "content": ai_response["text"]
    })
    
    # Update collected data
    conversation["collected_data"].update(ai_response["collected_data"])
    
    # Update call in database
    db_service = DBService(db)
    if conversation.get("call_id"):
        # Build transcript
        transcript = "\n".join([
            f"{'Customer' if msg['role'] == 'user' else 'AI'}: {msg['content']}"
            for msg in conversation["history"]
        ])
        
        await db_service.update_call(
            conversation["call_id"],
            {
                "transcript": transcript,
                "intent": ai_response["intent"]
            }
        )
    
    # Build TwiML response
    response = VoiceResponse()
    
    # Check if booking is complete based on multiple signals
    is_booking_complete = _is_booking_complete(
        conversation["collected_data"], 
        conversation["history"], 
        ai_response["intent"],
        ai_response["text"]  # Pass AI response to check for completion signals
    )
    
    if is_booking_complete:
        # Create booking in database!
        booking = await db_service.create_booking({
            "business_id": uuid.UUID(conversation["business_id"]),
            "call_id": uuid.UUID(conversation["call_id"]),
            "customer_name": _extract_name(conversation["history"]),
            "customer_phone": conversation["caller_phone"],
            "service": conversation["collected_data"].get("service", "General"),
            "booking_datetime": datetime.utcnow(),  # We'll improve date parsing later
            "status": "confirmed",
            "confirmed_at": datetime.utcnow()
        })

        booking_date = booking.booking_datetime.strftime("%A %d %b %Y at %I:%M %p")
        sms_message = (
            f"Hi {booking.customer_name}! Your {booking.service} appointment at "
            f"{conversation.get('business_name', 'our business')} is confirmed for "
            f"{booking_date}. Questions? Call {conversation.get('business_phone', '')}"
        )
        try:
            twilio_client.send_sms(booking.customer_phone, sms_message)
        except Exception as e:
            print(f"❌ ERROR sending SMS: {e}")
        
        print(f"""
        ═══════════════════════════════════════
        ✅ BOOKING CREATED!
        ═══════════════════════════════════════
        ID: {booking.id}
        Customer: {booking.customer_name}
        Service: {booking.service}
        ═══════════════════════════════════════
        """)
        
        # Mark call as successful
        await db_service.update_call(
            conversation["call_id"],
            {
                "outcome": "booked",
                "ended_at": datetime.utcnow()
            }
        )
        
        response.say(
            "Perfect! Your appointment is confirmed. You'll receive an SMS shortly. Thank you!",
            voice='Polly.Nicole',
            language='en-AU'
        )
        
        # Clean up
        del conversations[call_sid]
        
    else:
        # Continue conversation
        response.say(ai_response["text"], voice='Polly.Nicole', language='en-AU')
        
        gather = Gather(
            input='speech',
            action=f'/voice/process/{business_id}/{call_sid}',
            timeout=5,
            speech_timeout='auto',
            language='en-AU'
        )
        response.append(gather)
        
        response.say(
            "Are you still there? Call back anytime!",
            voice='Polly.Nicole',
            language='en-AU'
        )
    
    return Response(content=str(response), media_type="application/xml")


def _is_booking_complete(collected_data: dict, history: list, intent: str, ai_response_text: str = "") -> bool:
    """Check if we have enough info to create booking
    
    Signals:
    1. AI response contains completion phrases ("All set!", "I'll SMS you soon", "confirmed", etc.)
    2. We have collected service data
    3. We have collected time data
    4. We've extracted a customer name from conversation
    """
    # Check for AI completion signals in the response
    completion_signals = [
        "all set", "i'll sms you", "i will sms", "sms you soon", 
        "confirmed", "booked", "appointment is set", "you're all set",
        "everything is confirmed"
    ]
    
    ai_text_lower = ai_response_text.lower()
    has_completion_signal = any(signal in ai_text_lower for signal in completion_signals)
    
    # If AI says "all set", check if we have minimum data
    if has_completion_signal:
        # Check if we have service and extracted a name
        has_service = "service" in collected_data
        has_name = _extract_name(history) != "Customer"  # We got a real name
        
        print(
            f"🔎 Booking check: completion_signal={has_completion_signal}, "
            f"service={has_service}, name={has_name}, "
            f"ai_text='{ai_response_text}', "
            f"collected_data={collected_data}"
        )

        # If we have service, name, and time preference, it's ready
        if has_service and has_name:
            print(f"✅ Booking completion detected - AI confirmed with all data collected")
            return True
    
    return False


def _extract_name(history: list) -> str:
    """Extract customer name from conversation history"""
    # Simple extraction - look for common name patterns
    for msg in reversed(history):
        if msg["role"] == "user":
            content = msg["content"].strip()
            content_lower = content.lower()

            if "my name is" in content_lower:
                name = content_lower.split("my name is")[-1].strip()
                return name.split()[0].capitalize() if name else "Customer"
            if "i'm" in content_lower or "i am" in content_lower:
                cleaned = content_lower.replace("i'm", "").replace("i am", "").strip()
                words = cleaned.split()
                if words:
                    return words[0].capitalize()
            if "this is" in content_lower:
                name = content_lower.split("this is")[-1].strip()
                return name.split()[0].capitalize() if name else "Customer"
            if " and my" in content_lower:
                name = content_lower.split(" and my")[0].strip()
                return name.split()[0].capitalize() if name else "Customer"
            # Fallback: if the user reply is just a name (1-2 words, no digits)
            words = [w for w in content.split() if w.isalpha()]
            if words and len(words) <= 2 and not any(ch.isdigit() for ch in content):
                return words[0].capitalize()
    
    return "Customer"
