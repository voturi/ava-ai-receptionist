"""
Call Session Manager for Streaming Voice Calls.

Manages state for bidirectional WebSocket connections with Twilio Media Streams.
Each call gets its own CallSession instance that handles:
- Audio streaming to/from Twilio
- STT connection (Deepgram Nova) - Phase 2
- TTS connection (Deepgram Aura) - Phase 3
- Conversation state and history
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Optional
from zoneinfo import ZoneInfo

from app.integrations.stt import DeepgramStreamingSTT
from app.integrations.stt.deepgram_streaming import TranscriptResult, STTConfig
from app.integrations.tts import DeepgramStreamingTTS, TTSConfig
from app.services.streaming_ai_service import streaming_ai_service
from app.integrations.twilio_client import twilio_client
from app.integrations.providers.registry import resolve_provider, get_provider_config
from app.integrations.providers.base import BookingContext, CustomerInfo
from app.core.database import AsyncSessionLocal
from app.services.db_service import DBService
from app.tools.tool_router import ToolRouter
from app.tools.tool_definitions import TOOLS

if TYPE_CHECKING:
    from fastapi import WebSocket


@dataclass
class CallMetrics:
    """Track latency and quality metrics for a call."""

    call_sid: str
    started_at: Optional[datetime] = None
    first_audio_received_at: Optional[datetime] = None
    first_transcript_at: Optional[datetime] = None
    first_response_audio_at: Optional[datetime] = None
    barge_in_count: int = 0
    total_user_utterances: int = 0
    total_ai_responses: int = 0

    @property
    def time_to_first_transcript_ms(self) -> Optional[float]:
        if self.first_audio_received_at and self.first_transcript_at:
            delta = self.first_transcript_at - self.first_audio_received_at
            return delta.total_seconds() * 1000
        return None

    @property
    def time_to_first_response_ms(self) -> Optional[float]:
        if self.first_transcript_at and self.first_response_audio_at:
            delta = self.first_response_audio_at - self.first_transcript_at
            return delta.total_seconds() * 1000
        return None

    def log_summary(self) -> None:
        """Log metrics summary."""
        ttft = self.time_to_first_transcript_ms
        ttfr = self.time_to_first_response_ms
        print(f"""
        ════════════════════════════════════════
        📊 CALL METRICS: {self.call_sid}
        ════════════════════════════════════════
        Time to First Transcript: {f'{ttft:.0f}ms' if ttft else 'N/A'}
        Time to First Response:   {f'{ttfr:.0f}ms' if ttfr else 'N/A'}
        User Utterances:          {self.total_user_utterances}
        AI Responses:             {self.total_ai_responses}
        Barge-ins:                {self.barge_in_count}
        ════════════════════════════════════════
        """)


@dataclass
class CallSession:
    """
    Manages state for a single streaming voice call.

    Handles bidirectional audio streaming between Twilio Media Streams
    and our STT/TTS providers.
    """

    call_sid: str
    business_id: str
    websocket: WebSocket

    # Database reference
    call_id: Optional[str] = None

    # Business context
    business_name: str = "our business"
    business_config: dict = field(default_factory=dict)

    # Stream metadata (set on Twilio 'start' message)
    stream_sid: Optional[str] = None
    audio_track: str = "inbound"

    # Caller info
    caller_phone: Optional[str] = None

    # Conversation state
    conversation_history: list = field(default_factory=list)
    collected_data: dict = field(default_factory=dict)
    current_transcript: str = ""
    booking_created: bool = False

    # Speaking state
    is_user_speaking: bool = False
    is_ai_speaking: bool = False
    pending_end_call: bool = False
    pending_end_mark: str = "end_call"

    # Metrics
    metrics: CallMetrics = field(default_factory=lambda: CallMetrics(call_sid=""))

    # STT/TTS connections (populated in Phase 2/3)
    stt_connection: Any = None
    tts_connection: Any = None

    # Background tasks
    _tasks: list = field(default_factory=list)
    _end_call_task: Optional[asyncio.Task] = None

    # Tooling
    tool_router: ToolRouter = field(default_factory=ToolRouter)
    tool_context: dict = field(default_factory=dict)
    tool_history: list = field(default_factory=list)

    def __post_init__(self):
        self.metrics = CallMetrics(call_sid=self.call_sid)
        self.metrics.started_at = datetime.utcnow()

    async def initialize(self) -> None:
        """
        Initialize the call session.

        Sets up STT and TTS connections, plays greeting.
        """
        print(f"""
        ════════════════════════════════════════
        🎙️ STREAMING CALL STARTED
        ════════════════════════════════════════
        Call SID:    {self.call_sid}
        Business:    {self.business_name}
        Time:        {datetime.now().strftime('%H:%M:%S')}
        ════════════════════════════════════════
        """)

        # Load business context
        await self._load_business_context()

        # Initialize STT connection (Deepgram Nova)
        await self._connect_stt()

        # Initialize TTS connection (Deepgram Aura)
        await self._connect_tts()

        # Play greeting audio
        await self._play_greeting()

    async def handle_twilio_message(self, message: dict) -> None:
        """
        Process incoming Twilio WebSocket message.

        Message types:
        - connected: WebSocket connection established
        - start: Stream metadata
        - media: Audio data
        - stop: Stream ended
        """
        event = message.get("event")

        if event == "connected":
            print(f"🔌 Twilio WebSocket connected: {self.call_sid}")

        elif event == "start":
            start_data = message.get("start", {})
            self.stream_sid = start_data.get("streamSid")
            self.audio_track = start_data.get("track", "inbound")

            # Extract custom parameters if provided
            custom_params = start_data.get("customParameters", {})
            self.caller_phone = custom_params.get("caller_phone")

            print(f"🎙️ Media stream started: {self.stream_sid}")

        elif event == "media":
            # Audio data from caller
            media_data = message.get("media", {})
            audio_payload = media_data.get("payload", "")  # base64 μ-law

            if audio_payload:
                await self._handle_incoming_audio(audio_payload)

        elif event == "stop":
            print(f"⏹️ Media stream stopped: {self.call_sid}")

        elif event == "mark":
            # Mark event - audio playback reached a marker
            mark_name = message.get("mark", {}).get("name")
            print(f"📍 Mark reached: {mark_name}")
            if self.pending_end_call and mark_name == self.pending_end_mark:
                print("📞 End-of-call mark reached, ending call")
                self.pending_end_call = False
                if self._end_call_task and not self._end_call_task.done():
                    self._end_call_task.cancel()
                await self._end_call()

    async def send_audio(self, audio_bytes: bytes) -> None:
        """
        Send audio to Twilio for playback to caller.

        Audio must be μ-law encoded, 8kHz, mono.
        """
        if not self.stream_sid:
            print("⚠️ Cannot send audio: stream not started")
            return

        payload = base64.b64encode(audio_bytes).decode("utf-8")

        await self.websocket.send_json({
            "event": "media",
            "streamSid": self.stream_sid,
            "media": {
                "payload": payload,
            },
        })

    async def send_mark(self, name: str) -> None:
        """
        Send a mark event to track audio playback position.

        Twilio will send back a 'mark' event when playback reaches this point.
        """
        if not self.stream_sid:
            return

        await self.websocket.send_json({
            "event": "mark",
            "streamSid": self.stream_sid,
            "mark": {
                "name": name,
            },
        })

    async def clear_audio_buffer(self) -> None:
        """
        Clear Twilio's audio playback buffer.

        Used for barge-in: stops current AI speech when user interrupts.
        """
        if not self.stream_sid:
            return

        await self.websocket.send_json({
            "event": "clear",
            "streamSid": self.stream_sid,
        })
        print("🛑 Audio buffer cleared (barge-in)")

    async def cleanup(self) -> None:
        """Clean up resources when call ends."""
        # Cancel background tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()

        # Close STT connection (Phase 2)
        if self.stt_connection:
            try:
                await self.stt_connection.close()
            except Exception as e:
                print(f"⚠️ Error closing STT: {e}")

        # Close TTS connection (Phase 3)
        if self.tts_connection:
            try:
                await self.tts_connection.close()
            except Exception as e:
                print(f"⚠️ Error closing TTS: {e}")

        # Log metrics
        self.metrics.log_summary()

        print(f"🧹 Session cleaned up: {self.call_sid}")

    # ─────────────────────────────────────────────────────────────────
    # Private Methods
    # ─────────────────────────────────────────────────────────────────

    async def _connect_stt(self) -> None:
        """Connect to Deepgram streaming STT."""
        try:
            self.stt_connection = DeepgramStreamingSTT(
                on_transcript=self._on_transcript,
                on_utterance_end=self._on_utterance_end,
                on_speech_started=self._on_speech_started,
                config=STTConfig(
                    model="nova-2",
                    language="en-AU",
                    sample_rate=8000,
                    encoding="mulaw",
                    interim_results=True,
                    utterance_end_ms=2000,  # Wait 2s of silence before UtteranceEnd (allows thinking pauses)
                    endpointing=1000,  # 1s silence for final transcript chunks
                ),
            )
            await self.stt_connection.connect()
            print(f"🎤 STT connected for call {self.call_sid}")
        except Exception as e:
            print(f"❌ Failed to connect STT: {e}")
            self.stt_connection = None

    async def _connect_tts(self) -> None:
        """Connect to Deepgram streaming TTS."""
        try:
            self.tts_connection = DeepgramStreamingTTS(
                on_audio=self._on_tts_audio,
                on_complete=self._on_tts_complete,
                config=TTSConfig(
                    model="aura-asteria-en",  # Default voice
                    sample_rate=8000,
                    encoding="mulaw",
                ),
            )
            await self.tts_connection.connect()
            print(f"🔊 TTS connected for call {self.call_sid}")
        except Exception as e:
            print(f"❌ Failed to connect TTS: {e}")
            self.tts_connection = None

    async def _on_tts_audio(self, audio_bytes: bytes) -> None:
        """Handle audio chunk from TTS - forward to Twilio."""
        self.is_ai_speaking = True

        # Track first response audio
        if self.metrics.first_response_audio_at is None:
            self.metrics.first_response_audio_at = datetime.utcnow()
            if self.metrics.first_transcript_at:
                latency = (self.metrics.first_response_audio_at - self.metrics.first_transcript_at).total_seconds() * 1000
                print(f"⚡ Time to first response audio: {latency:.0f}ms")

        # Send to Twilio
        await self.send_audio(audio_bytes)

    async def _on_tts_complete(self) -> None:
        """Handle TTS completion."""
        self.is_ai_speaking = False
        self.metrics.total_ai_responses += 1
        print("🔊 TTS utterance complete")
        if self.pending_end_call:
            await self.send_mark(self.pending_end_mark)

    async def speak(self, text: str) -> None:
        """
        Speak text to the caller via TTS.

        Sends text to Deepgram TTS which streams audio back to Twilio.
        """
        if not self.tts_connection or not self.tts_connection.is_connected:
            print("⚠️ TTS not connected, cannot speak")
            return

        print(f"🗣️ Speaking: {text}")

        # Add to conversation history
        self.conversation_history.append({
            "role": "assistant",
            "content": text,
        })

        # Send text and flush
        await self.tts_connection.send_text(text)
        await self.tts_connection.flush()

    async def speak_streaming(self, text_chunks: list[str]) -> None:
        """
        Speak text chunks as they arrive (for LLM streaming).

        Args:
            text_chunks: List of text chunks to speak
        """
        if not self.tts_connection or not self.tts_connection.is_connected:
            print("⚠️ TTS not connected, cannot speak")
            return

        full_text = ""
        for chunk in text_chunks:
            full_text += chunk
            await self.tts_connection.send_text(chunk)

        await self.tts_connection.flush()

        # Add to conversation history
        self.conversation_history.append({
            "role": "assistant",
            "content": full_text,
        })

    async def _process_with_llm(self, user_text: str) -> None:
        """
        Process user input with streaming LLM → TTS pipeline.

        This is the core of the streaming architecture:
        1. User text comes in from STT
        2. Stream to OpenAI for response
        3. As tokens arrive, immediately send to TTS
        4. TTS streams audio back to Twilio

        Result: <800ms to first audio byte
        """
        if not self.tts_connection or not self.tts_connection.is_connected:
            print("⚠️ TTS not connected, skipping LLM processing")
            return

        print(f"🤖 Processing with LLM: {user_text[:50]}...")

        # Track timing
        llm_start = datetime.utcnow()
        first_token_received = False
        full_response = ""

        try:
            prefetched_tools = await self._prefetch_tools(user_text)

            # Stream LLM response with tools (mid-stream tool calling)
            buffer = ""
            async for event in streaming_ai_service.stream_with_tools(
                user_message=user_text,
                conversation_history=self.conversation_history[:-1],
                business_profile=self._get_business_profile(),
                tools=TOOLS,
                tool_executor=self._execute_tool,
                max_tool_calls=2,
                prefetched_tools=prefetched_tools,
            ):
                if event.get("type") == "tool_call":
                    self.tool_history.append(event)
                    continue

                chunk = event.get("text", "")
                if not chunk:
                    continue

                # Track first token timing
                if not first_token_received:
                    first_token_received = True
                    llm_latency = (datetime.utcnow() - llm_start).total_seconds() * 1000
                    print(f"⚡ LLM first token: {llm_latency:.0f}ms")

                full_response += chunk
                buffer += chunk

                if streaming_ai_service._should_yield(buffer, min_size=10):
                    await self.tts_connection.send_text(buffer)
                    buffer = ""

            if buffer:
                await self.tts_connection.send_text(buffer)

            # Signal end of text to TTS
            await self.tts_connection.flush()

            # Add AI response to conversation history
            if full_response:
                self.conversation_history.append({
                    "role": "assistant",
                    "content": full_response,
                })

            total_latency = (datetime.utcnow() - llm_start).total_seconds() * 1000
            print(f"🤖 AI Response ({total_latency:.0f}ms): {full_response}")

            # Attempt booking creation if we have enough details
            await self._maybe_create_booking(full_response)

            # Update call record with transcript
            await self._update_call_record()

            # Check if we should end the call
            if self._should_end_call(user_text, full_response):
                # End call after Twilio playback reaches mark
                self.pending_end_call = True
                if self._end_call_task and not self._end_call_task.done():
                    self._end_call_task.cancel()
                self._end_call_task = asyncio.create_task(self._end_call_timeout())

        except Exception as e:
            print(f"❌ LLM processing error: {e}")
            # Fallback: speak an error message
            await self.speak("Sorry, I'm having trouble right now. Can you say that again?")

    def _should_end_call(self, user_text: str, ai_response: str) -> bool:
        """
        Detect if the conversation should end.

        Triggers on:
        - User says goodbye/thanks after booking confirmed
        - AI response contains "Goodbye" or similar farewell
        """
        user_lower = user_text.lower()
        ai_lower = ai_response.lower()

        # User farewell signals
        user_farewell = any(word in user_lower for word in [
            "thank you", "thanks", "bye", "goodbye", "that's all",
            "that's it", "cheers", "ta", "see you", "have a good"
        ])

        # AI farewell signals (end of conversation)
        ai_farewell = any(word in ai_lower for word in [
            "goodbye", "bye!", "see you", "take care", "all sorted"
        ])

        # End if either side clearly says goodbye/thanks
        if ai_farewell:
            print("📞 Call ending detected (AI farewell)")
            return True
        if user_farewell:
            print("📞 Call ending detected (User farewell)")
            return True

        return False

    async def _end_call(self) -> None:
        """End the call gracefully using Twilio API."""
        try:
            # Update call record with final data
            await self._update_call_record(outcome="completed", ended=True)

            print(f"📞 Ending call: {self.call_sid}")
            twilio_client.client.calls(self.call_sid).update(status="completed")
            print(f"✅ Call ended successfully")
        except Exception as e:
            print(f"❌ Error ending call: {e}")

    async def _update_call_record(
        self,
        outcome: Optional[str] = None,
        intent: Optional[str] = None,
        ended: bool = False,
    ) -> None:
        """
        Update the call record in the database.

        Called periodically to save transcript and at end to save outcome.
        """
        if not self.call_id:
            print("⚠️ No call_id, skipping database update")
            return

        try:
            # Build transcript from conversation history
            transcript = "\n".join([
                f"{'Customer' if msg['role'] == 'user' else 'AI'}: {msg['content']}"
                for msg in self.conversation_history
            ])

            # Build update data
            update_data = {"transcript": transcript}

            if outcome:
                update_data["outcome"] = outcome
            if intent:
                update_data["intent"] = intent
            if ended:
                update_data["ended_at"] = datetime.utcnow()

            # Update in database using a new session
            async with AsyncSessionLocal() as session:
                db_service = DBService(session)
                await db_service.update_call(self.call_id, update_data)

            print(f"💾 Call record updated: {self.call_id}")

        except Exception as e:
            print(f"❌ Error updating call record: {e}")

    async def _end_call_timeout(self, timeout_seconds: int = 2) -> None:
        """Fail-safe: end the call if the mark never arrives."""
        try:
            await asyncio.sleep(timeout_seconds)
            if self.pending_end_call:
                print("⏱️ End-of-call mark timeout, ending call")
                self.pending_end_call = False
                await self._end_call()
        except asyncio.CancelledError:
            pass

    async def _load_business_context(self) -> None:
        """Load business context from the database."""
        try:
            async with AsyncSessionLocal() as session:
                db_service = DBService(session)
                business = await db_service.get_business(self.business_id)
                if not business:
                    return
                policies = await db_service.get_policies(self.business_id, topic=None, limit=10)
                faqs = await db_service.get_faqs(self.business_id, topic=None, limit=10)
                self.business_name = business.name
                self.business_config = {
                    "business_name": business.name,
                    "industry": business.industry,
                    "ai_config": business.ai_config or {},
                    "services": business.services or [],
                    "working_hours": business.working_hours or {},
                    "policies_summary": self._format_policies_summary(policies),
                    "faqs_summary": self._format_faqs_summary(faqs),
                }
        except Exception as e:
            print(f"⚠️ Failed to load business context: {e}")

    def _get_business_profile(self) -> dict:
        """Return a business profile for prompt generation."""
        profile = dict(self.business_config or {})
        profile.setdefault("business_name", self.business_name)
        return profile

    async def _execute_tool(self, tool_name: str, arguments: dict) -> dict:
        """Execute a tool call with tenant context."""
        print(f"🛠️ Tool call: {tool_name} args={arguments} business_id={self.business_id}")
        result = await self.tool_router.execute(
            tool_name,
            arguments,
            business_id=self.business_id,
            caller_phone=self.caller_phone,
        )
        print(f"🧾 Tool result: {tool_name} => {result}")
        self.tool_context[tool_name] = result
        return result

    async def _maybe_create_booking(self, ai_response_text: str) -> None:
        """Create a booking if conversation indicates completion and data is sufficient."""
        if self.booking_created:
            return
        if not self.call_id:
            return

        service = self._extract_service_from_history()
        collected = {"service": service} if service else {}

        requested_dt = self._extract_datetime_from_history(self.conversation_history)
        if requested_dt is None and ai_response_text:
            requested_dt = self._extract_datetime_from_text(ai_response_text)
        customer_name = self._extract_name(self.conversation_history)
        customer_phone = self.caller_phone or ""
        if customer_name == "Customer" or not customer_phone:
            return

        has_datetime = requested_dt is not None
        if not (service and has_datetime):
            return

        provider_config = get_provider_config(self.business_config.get("ai_config"))
        provider = resolve_provider(provider_config)
        context = BookingContext(
            business_id=self.business_id,
            business_name=self.business_name,
            service=service or "General",
            requested_datetime=requested_dt,
            customer=CustomerInfo(
                name=customer_name,
                phone=customer_phone,
            ),
            metadata=provider_config,
        )

        availability = await provider.check_availability(context)
        if not availability.available:
            return

        intent = await provider.create_booking(context)
        if intent.status == "declined":
            return

        booking_datetime = requested_dt or self._local_now()
        internal_notes = None
        if intent.external_reference:
            internal_notes = f"Provider reference: {intent.external_reference}"

        async with AsyncSessionLocal() as session:
            db_service = DBService(session)
            booking = await db_service.create_booking({
                "business_id": self.business_id,
                "call_id": self.call_id,
                "customer_name": customer_name,
                "customer_phone": customer_phone,
                "service": service or "General",
                "booking_datetime": booking_datetime,
                "status": intent.status,
                "confirmed_at": datetime.utcnow() if intent.status == "confirmed" else None,
                "internal_notes": internal_notes,
                "customer_notes": self._extract_issue_summary(),
            })

        self.booking_created = True

        try:
            booking_date = booking_datetime.strftime("%A %d %b %Y at %I:%M %p")
            sms_message = (
                f"Hi {customer_name}! Your {service or 'service'} appointment at "
                f"{self.business_name} is confirmed for {booking_date}."
            )
            if intent.message_override:
                sms_message = intent.message_override
            twilio_client.send_sms(customer_phone, sms_message)
        except Exception as e:
            print(f"❌ ERROR sending SMS: {e}")

        print(f"✅ BOOKING CREATED: {booking.id} ({customer_name}, {service})")

    def _is_booking_complete(self, collected_data: dict, history: list, ai_response_text: str = "") -> bool:
        completion_signals = [
            "all set", "i'll sms you", "i will sms", "sms you soon",
            "confirmed", "booked", "appointment is set", "you're all set",
            "everything is confirmed", "i'll book", "i will book",
            "i'll schedule", "i will schedule", "thanks for confirming"
        ]
        ai_text_lower = ai_response_text.lower()
        has_completion_signal = any(signal in ai_text_lower for signal in completion_signals)
        if not has_completion_signal:
            return False

        has_service = "service" in collected_data and collected_data["service"]
        has_name = self._extract_name(history) != "Customer"
        has_phone = bool(self.caller_phone)
        has_datetime = (
            self._extract_datetime_from_history(history) is not None
            or self._extract_datetime_from_text(ai_response_text) is not None
        )

        if has_service and has_name and has_phone and has_datetime:
            return True

        print(
            f"🔎 Booking incomplete: service={has_service} name={has_name} "
            f"phone={has_phone} datetime={has_datetime}"
        )
        return False

    def _extract_name(self, history: list) -> str:
        for msg in reversed(history):
            if msg.get("role") == "user":
                content = msg.get("content", "").strip()
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
                words = [w for w in content.split() if w.isalpha()]
                if words and len(words) <= 2 and not any(ch.isdigit() for ch in content):
                    return words[0].capitalize()
        return "Customer"

    def _extract_datetime_from_history(self, history: list) -> datetime | None:
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

            now = self._local_now()
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

    def _extract_datetime_from_text(self, text: str) -> datetime | None:
        if not text:
            return None
        content_lower = text.lower()
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
        day = None
        for name, idx in weekdays.items():
            if name in content_lower:
                day = idx
                break
        time_match = time_pattern.search(content_lower)
        if day is None and not time_match and "tomorrow" not in content_lower:
            return None
        now = self._local_now()
        target_date = now
        if "tomorrow" in content_lower:
            target_date = now + timedelta(days=1)
        elif day is not None:
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

    def _local_now(self) -> datetime:
        """Return current time in Australia/Sydney as naive local time."""
        local = datetime.now(ZoneInfo("Australia/Sydney"))
        return local.replace(tzinfo=None)

    def _extract_service_from_history(self) -> Optional[str]:
        services = self.business_config.get("services") or []
        if not services:
            return None
        history_text = " ".join(
            msg.get("content", "").lower() for msg in self.conversation_history
        )
        for service in services:
            if isinstance(service, dict):
                name = str(service.get("name", "")).lower()
            else:
                name = str(service).lower()
            if name and name in history_text:
                return str(service.get("name")) if isinstance(service, dict) else str(service)
        return None

    def _extract_issue_summary(self) -> Optional[str]:
        """Return the most recent user utterance as issue summary."""
        for msg in reversed(self.conversation_history):
            if msg.get("role") == "user":
                content = msg.get("content", "").strip()
                return content[:500] if content else None
        return None

    def _format_policies_summary(self, policies: list) -> str:
        if not policies:
            return "Not provided."
        parts = []
        for policy in policies:
            parts.append(f"{policy.topic}: {policy.content}")
        return " | ".join(parts)[:1200]

    def _format_faqs_summary(self, faqs: list) -> str:
        if not faqs:
            return "Not provided."
        parts = []
        for faq in faqs:
            parts.append(f"Q: {faq.question} A: {faq.answer}")
        return " | ".join(parts)[:1200]

    async def _prefetch_tools(self, user_text: str) -> list[dict]:
        """Deterministically prefetch tools for common intents (MVP heuristic)."""
        text = user_text.lower()
        prefetched: list[dict] = []
        if any(
            phrase in text for phrase in [
                "booking status",
                "status of my booking",
                "booking confirmed",
                "is my booking confirmed",
                "did my booking go through",
                "confirmation",
            ]
        ):
            result = await self._execute_tool("get_latest_booking", {"customer_phone": self.caller_phone})
            prefetched.append({"name": "get_latest_booking", "arguments": {"customer_phone": self.caller_phone}, "result": result})

        return prefetched

    async def _on_transcript(self, result: TranscriptResult) -> None:
        """Handle transcript from STT."""
        if result.is_final and result.text.strip():
            # Accumulate final transcripts (Deepgram sends these periodically)
            # Don't process yet - wait for UtteranceEnd
            if self.current_transcript:
                self.current_transcript += " " + result.text
            else:
                self.current_transcript = result.text

            if self.metrics.first_transcript_at is None:
                self.metrics.first_transcript_at = datetime.utcnow()
                if self.metrics.first_audio_received_at:
                    latency = (self.metrics.first_transcript_at - self.metrics.first_audio_received_at).total_seconds() * 1000
                    print(f"⚡ Time to first transcript: {latency:.0f}ms")

            print(f"🎤 [FINAL] {result.text}")
            print(f"📝 [ACCUMULATED] {self.current_transcript}")

        else:
            # Interim result - show what user is currently saying
            print(f"🎤 [PARTIAL] {result.text}")

    async def _on_utterance_end(self) -> None:
        """
        Handle end of user utterance (VAD detected silence).

        This is the RIGHT time to process - user has actually stopped speaking.
        """
        self.is_user_speaking = False

        if self.current_transcript and self.current_transcript.strip():
            full_utterance = self.current_transcript.strip()
            self.current_transcript = ""  # Clear for next utterance

            print(f"🛑 Utterance complete: {full_utterance}")

            self.metrics.total_user_utterances += 1

            # Add to conversation history
            self.conversation_history.append({
                "role": "user",
                "content": full_utterance,
            })

            # NOW process with LLM (user has finished speaking)
            asyncio.create_task(self._process_with_llm(full_utterance))
        else:
            print(f"🛑 Utterance end (no transcript)")

    async def _on_speech_started(self) -> None:
        """Handle start of user speech."""
        self.is_user_speaking = True

        # Barge-in: If AI is speaking and user starts talking, clear buffer
        if self.is_ai_speaking:
            self.metrics.barge_in_count += 1
            print(f"🛑 BARGE-IN detected! Clearing audio buffer...")
            await self.clear_audio_buffer()
            self.is_ai_speaking = False

    async def _handle_incoming_audio(self, base64_audio: str) -> None:
        """
        Process incoming audio from Twilio.

        Decodes base64 μ-law audio and forwards to Deepgram STT.
        """
        # Track first audio for metrics
        if self.metrics.first_audio_received_at is None:
            self.metrics.first_audio_received_at = datetime.utcnow()
            print("🎤 First audio received from caller")

        # Decode and forward to STT
        if self.stt_connection and self.stt_connection.is_connected:
            audio_bytes = base64.b64decode(base64_audio)
            await self.stt_connection.send_audio(audio_bytes)

    async def _play_greeting(self) -> None:
        """
        Play greeting audio to caller.

        Phase 1: Uses pre-cached greeting audio URL (loaded via TwiML before stream).
        Phase 3: Will stream greeting via TTS WebSocket.
        """
        # In Phase 1, greeting is played via TwiML before stream starts
        # This method is a placeholder for Phase 3 streaming greeting
        greeting_text = f"G'day! Welcome to {self.business_name}. How can I help you today?"

        self.conversation_history.append({
            "role": "assistant",
            "content": greeting_text,
        })

        print(f"🗣️ Greeting: {greeting_text}")


# ─────────────────────────────────────────────────────────────────────
# Session Registry
# ─────────────────────────────────────────────────────────────────────

# Active call sessions (in-memory for now, Redis in production)
_sessions: dict[str, CallSession] = {}


def get_session(call_sid: str) -> Optional[CallSession]:
    """Get an active call session by call SID."""
    return _sessions.get(call_sid)


def register_session(session: CallSession) -> None:
    """Register a new call session."""
    _sessions[session.call_sid] = session
    print(f"📝 Session registered: {session.call_sid} (total: {len(_sessions)})")


def unregister_session(call_sid: str) -> Optional[CallSession]:
    """Remove and return a call session."""
    session = _sessions.pop(call_sid, None)
    if session:
        print(f"📝 Session unregistered: {call_sid} (total: {len(_sessions)})")
    return session


def get_active_session_count() -> int:
    """Get count of active sessions."""
    return len(_sessions)
