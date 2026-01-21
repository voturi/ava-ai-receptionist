"""
Twilio Media Streams WebSocket Handler.

Handles bidirectional audio streaming for real-time voice conversations.
This replaces the webhook-based approach for lower latency (<800ms vs ~2s).

Flow:
1. Twilio calls /stream/incoming/{business_id} webhook
2. We return TwiML that connects to our WebSocket at /stream/ws/{business_id}/{call_sid}
3. Bidirectional audio streams over WebSocket:
   - Inbound: Caller audio → Deepgram STT → LLM → Deepgram TTS
   - Outbound: TTS audio → Caller

References:
- https://www.twilio.com/docs/voice/media-streams
- https://www.twilio.com/docs/voice/twiml/stream
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream

from app.core.database import get_db
from app.services.db_service import DBService
from app.services.call_session import (
    CallSession,
    get_session,
    register_session,
    unregister_session,
    get_active_session_count,
)

router = APIRouter()


@router.post("/incoming/{business_id}")
async def incoming_call_stream(
    business_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Twilio webhook for incoming calls - initiates Media Stream.

    Returns TwiML that:
    1. Optionally plays a greeting (from cached audio URL)
    2. Connects to our WebSocket for bidirectional streaming
    """
    form = await request.form()
    call_sid = form.get("CallSid")
    caller_phone = form.get("From")
    twilio_number = form.get("To")

    print(f"""
    ════════════════════════════════════════
    📞 NEW STREAMING CALL
    ════════════════════════════════════════
    Business ID: {business_id}
    Call SID:    {call_sid}
    Caller:      {caller_phone}
    To:          {twilio_number}
    Time:        {datetime.now().strftime('%H:%M:%S')}
    ════════════════════════════════════════
    """)

    # Get business from database
    db_service = DBService(db)
    business = await db_service.get_business_by_phone(twilio_number)

    if not business:
        business = await db_service.get_business(business_id)

    if not business:
        # Return error response
        response = VoiceResponse()
        response.say(
            "Sorry, this number is not configured. Please contact support.",
            voice="Polly.Nicole",
            language="en-AU",
        )
        return Response(content=str(response), media_type="application/xml")

    # Create call record in database
    call = None
    try:
        call = await db_service.create_call({
            "business_id": business.id,
            "call_sid": call_sid,
            "caller_phone": caller_phone,
            "started_at": datetime.utcnow(),
            "intent": "unknown",
            "outcome": "in_progress",
        })
        print(f"💾 Call saved: {call.id}")
    except Exception as e:
        print(f"❌ Error creating call record: {e}")

    # Build WebSocket URL
    # Use X-Forwarded-Host for production (behind load balancer)
    host = request.headers.get("X-Forwarded-Host") or request.headers.get("host", "localhost:8000")

    # Determine protocol (wss for production, ws for local)
    proto = "wss" if request.headers.get("X-Forwarded-Proto") == "https" else "ws"
    if "localhost" in host or "127.0.0.1" in host:
        proto = "ws"

    ws_url = f"{proto}://{host}/stream/ws/{business_id}/{call_sid}"

    print(f"🔗 WebSocket URL: {ws_url}")

    # Build TwiML response
    response = VoiceResponse()

    # Play cached greeting if available (faster than streaming)
    ai_config = business.ai_config or {}
    greeting_url = ai_config.get("voice", {}).get("greeting_audio_url")

    if greeting_url:
        response.play(greeting_url)
    else:
        # Fallback to native TTS
        greeting_text = f"G'day! Welcome to {business.name}. How can I help you today?"
        response.say(greeting_text, voice="Polly.Nicole", language="en-AU")

    # Connect to our WebSocket for bidirectional streaming
    connect = Connect()
    stream = Stream(url=ws_url)

    # Pass custom parameters to the WebSocket handler
    call_id_str = str(call.id) if call else ""
    stream.parameter(name="business_id", value=str(business.id))
    stream.parameter(name="business_name", value=business.name)
    stream.parameter(name="caller_phone", value=caller_phone or "")
    stream.parameter(name="call_id", value=call_id_str)

    print(f"📋 Stream params: call_id={call_id_str}")

    connect.append(stream)
    response.append(connect)

    print(f"📱 TwiML response built with WebSocket stream")
    return Response(content=str(response), media_type="application/xml")


@router.websocket("/ws/{business_id}/{call_sid}")
async def media_stream_websocket(
    websocket: WebSocket,
    business_id: str,
    call_sid: str,
):
    """
    Bidirectional WebSocket handler for Twilio Media Streams.

    Receives:
    - 'connected': WebSocket established
    - 'start': Stream metadata and custom parameters
    - 'media': Audio chunks (base64 μ-law, 8kHz)
    - 'stop': Stream ended

    Sends:
    - 'media': Audio to play to caller (base64 μ-law, 8kHz)
    - 'mark': Markers to track playback position
    - 'clear': Clear audio buffer (for barge-in)
    """
    await websocket.accept()

    print(f"🔌 WebSocket accepted: {call_sid}")

    # Create session (business context will be set from 'start' message)
    session = CallSession(
        call_sid=call_sid,
        business_id=business_id,
        websocket=websocket,
    )

    try:
        # Main message loop
        while True:
            try:
                # Receive message (text for JSON, could also be binary)
                raw_message = await websocket.receive_text()
                message = json.loads(raw_message)

                # Handle 'start' message specially to initialize session
                if message.get("event") == "start":
                    start_data = message.get("start", {})
                    custom_params = start_data.get("customParameters", {})

                    # Update session with business context
                    session.business_name = custom_params.get("business_name", "our business")
                    session.caller_phone = custom_params.get("caller_phone")
                    session.call_id = custom_params.get("call_id")

                    print(f"📋 Session initialized: call_id={session.call_id}, business={session.business_name}")

                    # Register session after we have full context
                    register_session(session)

                    # Initialize STT/TTS connections
                    await session.initialize()

                # Process message
                await session.handle_twilio_message(message)

            except json.JSONDecodeError as e:
                print(f"⚠️ Invalid JSON from Twilio: {e}")

    except WebSocketDisconnect:
        print(f"📞 WebSocket disconnected: {call_sid}")

    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup
        await session.cleanup()
        unregister_session(call_sid)


@router.get("/status")
async def stream_status():
    """
    Get status of streaming infrastructure.

    Returns count of active streaming sessions.
    """
    return {
        "status": "ok",
        "active_sessions": get_active_session_count(),
        "mode": "streaming",
    }
