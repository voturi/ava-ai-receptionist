from fastapi import APIRouter, Request, Response, Depends
from twilio.twiml.voice_response import VoiceResponse, Gather
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.ai_service import ai_service
from app.services.db_service import DBService
from app.integrations.twilio_client import twilio_client
from app.integrations.providers import BookingContext, CustomerInfo, get_provider_config, resolve_provider
from app.integrations.tts import AudioResult, get_voice_config as get_tts_config
from app.integrations.tts import resolve_provider as resolve_tts_provider
from app.core.database import get_db
import json
import uuid
import re
import asyncio

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
    
    provider_config = get_provider_config(business.ai_config)
    provider = resolve_provider(provider_config)

    # Initialize conversation in memory
    conversations[call_sid] = {
        "call_id": str(call.id),
        "history": [],
        "collected_data": {},
        "business_id": str(business.id),
        "business_name": business.name,
        "services": business.services or [],
        "business_phone": business.twilio_number,
        "caller_phone": caller_phone,
        "provider": provider,
        "provider_config": provider_config,
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
        voice_config = get_tts_config(business.ai_config)
        cached_greeting_url = (business.ai_config or {}).get("voice", {}).get("greeting_audio_url")
        if cached_greeting_url:
            response.play(cached_greeting_url)
        else:
            tts_provider = resolve_tts_provider(voice_config)
            if not await _play_tts_response(response, ai_response["text"], business.ai_config or {}):
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
    
    db_service = DBService(db)
    business = await db_service.get_business(conversation.get("business_id", ""))

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
    conversation["last_ai_response"] = ai_response["text"]
    
    # Update call in database
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
        provider = conversation.get("provider")
        requested_dt = _extract_datetime_from_history(conversation["history"])
        context = BookingContext(
            business_id=conversation["business_id"],
            business_name=conversation["business_name"],
            service=conversation["collected_data"].get("service", "General"),
            requested_datetime=requested_dt,
            customer=CustomerInfo(
                name=_extract_name(conversation["history"]),
                phone=conversation["caller_phone"],
            ),
            metadata=conversation.get("provider_config", {}),
        )

        availability = await provider.check_availability(context)
        if not availability.available:
            response.say(
                availability.reason or "Thanks! That time isn't available. Could you pick another time?",
                voice='Polly.Nicole',
                language='en-AU'
            )
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

        intent = await provider.create_booking(context)
        if intent.status == "declined":
            response.say(
                intent.message_override or "Thanks! Could you share another time that works for you?",
                voice='Polly.Nicole',
                language='en-AU'
            )
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

        booking_datetime = requested_dt or datetime.utcnow()
        internal_notes = None
        if intent.external_reference:
            internal_notes = f"Provider reference: {intent.external_reference}"

        # Create booking in database!
        booking = await db_service.create_booking({
            "business_id": uuid.UUID(conversation["business_id"]),
            "call_id": uuid.UUID(conversation["call_id"]),
            "customer_name": context.customer.name,
            "customer_phone": context.customer.phone,
            "service": context.service,
            "booking_datetime": booking_datetime,
            "status": intent.status,
            "confirmed_at": datetime.utcnow() if intent.status == "confirmed" else None,
            "internal_notes": internal_notes
        })

        booking_date = booking.booking_datetime.strftime("%A %d %b %Y at %I:%M %p")
        sms_message = (
            f"Hi {booking.customer_name}! Your {booking.service} appointment at "
            f"{conversation.get('business_name', 'our business')} is confirmed for "
            f"{booking_date}. Questions? Call {conversation.get('business_phone', '')}"
        )
        if intent.message_override:
            sms_message = intent.message_override
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
        
        if intent.status == "confirmed":
            message_text = "Perfect! Your appointment is confirmed. You'll receive an SMS shortly. Thank you!"
        else:
            message_text = "Great! I'm sending you a link to confirm your booking. Please check your SMS."

        conversation["last_ai_response"] = message_text
        conversation["post_response_action"] = "end"

        tts_status = await _enqueue_tts_response(
            response,
            message_text,
            business.ai_config if business else {},
            business_id,
            call_sid,
            timeout_seconds=4.0,
        )
        if tts_status == "redirected":
            return Response(content=str(response), media_type="application/xml")
        if tts_status == "none":
            response.say(message_text, voice='Polly.Nicole', language='en-AU')
        
        # Clean up
        await provider.after_booking(context, str(booking.id))
        del conversations[call_sid]
        
    else:
        # Continue conversation
        conversation["post_response_action"] = "gather"
        tts_status = await _enqueue_tts_response(
            response,
            ai_response["text"],
            business.ai_config if business else {},
            business_id,
            call_sid,
            timeout_seconds=4.0,
        )
        if tts_status == "redirected":
            return Response(content=str(response), media_type="application/xml")
        if tts_status == "none":
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


@router.post("/response/{business_id}/{call_sid}")
async def tts_response(
    business_id: str,
    call_sid: str,
    db: AsyncSession = Depends(get_db),
):
    """Return the TTS response after playing a cached thinking clip."""
    conversation = conversations.get(call_sid, {})
    if not conversation:
        response = VoiceResponse()
        response.say(
            "Sorry, I lost track of our conversation. Please call back!",
            voice='Polly.Nicole',
            language='en-AU'
        )
        return Response(content=str(response), media_type="application/xml")

    db_service = DBService(db)
    business = await db_service.get_business(conversation.get("business_id", ""))
    response_text = conversation.get("last_ai_response", "")
    response = VoiceResponse()

    voice_config = get_tts_config(business.ai_config if business else {})
    tts_provider = resolve_tts_provider(voice_config)
    tts_audio = await _synthesize_with_timeout(tts_provider, response_text, voice_config, 8.0)
    if tts_audio.audio_url:
        response.play(tts_audio.audio_url)
    else:
        response.say(response_text, voice='Polly.Nicole', language='en-AU')

    if conversation.get("post_response_action") == "gather":
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
    else:
        del conversations[call_sid]

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


def _extract_datetime_from_history(history: list) -> datetime | None:
    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }

    time_pattern = re.compile(r"(\\d{1,2})(?::(\\d{2}))?\\s*(am|pm)?", re.IGNORECASE)

    for msg in reversed(history):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        content_lower = content.lower()

        day = None
        for name, idx in weekdays.items():
            if name in content_lower:
                day = idx
                break

        time_match = time_pattern.search(content_lower)
        if day is None and not time_match:
            continue

        now = datetime.utcnow()
        target_date = now
        if day is not None:
            days_ahead = (day - now.weekday() + 7) % 7
            if days_ahead == 0:
                days_ahead = 7
            if "next week" in content_lower:
                days_ahead += 7
            target_date = now + timedelta(days=days_ahead)

        hour = 9
        minute = 0
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
            meridiem = (time_match.group(3) or "").lower()
            if meridiem == "pm" and hour < 12:
                hour += 12
            if meridiem == "am" and hour == 12:
                hour = 0
        elif "afternoon" in content_lower or "arvo" in content_lower:
            hour = 15
        elif "morning" in content_lower:
            hour = 10

        return target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

    return None


async def _enqueue_tts_response(
    response: VoiceResponse,
    text: str,
    ai_config: dict,
    business_id: str,
    call_sid: str,
    timeout_seconds: float,
) -> str:
    """Play TTS audio or enqueue a follow-up response with a cached thinking clip."""
    voice_config = get_tts_config(ai_config or {})
    tts_provider = resolve_tts_provider(voice_config)
    tts_audio = await _synthesize_with_timeout(tts_provider, text, voice_config, timeout_seconds)
    if tts_audio.audio_url:
        response.play(tts_audio.audio_url)
        return "played"

    thinking_url = (ai_config or {}).get("voice", {}).get("thinking_audio_url")
    if thinking_url:
        response.play(thinking_url)
        response.redirect(f"/voice/response/{business_id}/{call_sid}")
        return "redirected"
    return "none"


async def _synthesize_with_timeout(provider, text: str, voice_config, timeout_seconds: float):
    """Run TTS synthesis with a timeout and return a safe AudioResult on failure."""
    try:
        return await asyncio.wait_for(
            provider.synthesize(text, voice_config),
            timeout=timeout_seconds,
        )
    except Exception:
        return AudioResult(
            audio_url=None,
            content_type=None,
            duration_ms=None,
            cached=False,
            error="tts_timeout_or_error",
        )
