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
from app.services import booking_logic
from app.services.conversation_engine import ConversationEngine, ConversationEngineConfig
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
class BookingState:
    """Structured state for a potential booking in this call.

    This will be populated progressively by workflows and helpers as
    we refactor booking logic away from ad-hoc extraction. For now it
    is introduced as a placeholder and does not change behaviour.
    """

    service: Optional[str] = None
    when: Optional[datetime] = None
    address: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    confirmed: bool = False
    booking_id: Optional[str] = None


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
    # Structured booking state (fields will be populated as we
    # refactor workflows). Currently not relied on for behaviour.
    booking_state: BookingState = field(default_factory=BookingState)
    # Last per-utterance intent from the detector
    last_intent: Optional[str] = None
    # Sticky primary intent/workflow for the call (e.g. "booking")
    primary_intent: Optional[str] = None

    # Speaking state
    is_user_speaking: bool = False
    is_ai_speaking: bool = False
    pending_end_call: bool = False
    pending_end_mark: str = "end_call"
    awaiting_final_confirmation: bool = False

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

    # Concurrency control (FIX #1: Prevent concurrent LLM processing)
    _processing_lock: Optional[asyncio.Lock] = None
    _utterance_debounce_task: Optional[asyncio.Task] = None
    _last_utterance_time: float = 0.0

    def __post_init__(self):
        self.metrics = CallMetrics(call_sid=self.call_sid)
        self.metrics.started_at = datetime.utcnow()
        # Initialize lock (can't use field(default_factory) for Lock)
        self._processing_lock = asyncio.Lock()

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
                    # Wait 3s of silence before UtteranceEnd (allows longer, more natural pauses)
                    utterance_end_ms=3000,
                    # Endpointing slightly higher than utterance_end_ms so Deepgram
                    # is less eager to cut the caller off mid-thought.
                    endpointing=3500,
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
        """Delegate LLM + tools + booking flow to ConversationEngine."""
        engine = ConversationEngine(ConversationEngineConfig(session=self))
        await engine.process_utterance(user_text)

    def _should_end_call(self, user_text: str, ai_response: str, booking_created: bool = None) -> bool:
        """
        Detect if the conversation should end.

        Args:
            user_text: User's most recent input
            ai_response: AI's most recent response
            booking_created: Whether a booking was just created (from local var)

        Triggers on:
        - User says goodbye/thanks (especially after booking)
        - AI response contains "Goodbye" or similar farewell
        """
        # Use passed parameter if provided (has fresher state), otherwise use instance var
        booking_state = booking_created if booking_created is not None else self.booking_created
        
        user_lower = user_text.lower()
        ai_lower = ai_response.lower()

        # User farewell signals - strong indicators to end call.
        # NOTE: Polite phrases like "thank you" or "thanks" can occur
        # mid-conversation, so we no longer treat them alone as a signal
        # to hang up. We only consider more explicit conversation-closure
        # phrases (bye / goodbye / that's all / that's it / see you / have a good...).
        has_goodbye = any(
            phrase in user_lower
            for phrase in [
                "bye",
                "goodbye",
                "that's all",
                "that's it",
                "see you",
                "have a good",
                "have a great",
            ]
        )
        user_farewell = has_goodbye

        # AI farewell signals (end of conversation)
        ai_farewell = any(word in ai_lower for word in [
            "goodbye", "bye!", "see you", "take care", "all sorted",
            "thank you for calling", "have a great", "thanks for calling",
            "you're all set", "appointment is confirmed"
        ])

        # DECISION LOGIC:
        # 1. User says goodbye - always end (most reliable signal)
        if user_farewell:
            print(f"📞 Call ending detected (User farewell): '{user_text}'")
            return True
        
        # 2. AI farewell after booking confirmed
        if ai_farewell and booking_state:
            print(f"📞 Call ending detected (AI farewell after booking): '{ai_response}'")
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

    async def _end_call_timeout(self, timeout_seconds: int = 6) -> None:
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
                    "twilio_number": business.twilio_number,
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

    async def _maybe_create_booking(self, ai_response_text: str, user_text: str | None = None) -> dict:
        """Create a booking if conversation indicates completion and data is sufficient.

        Delegates to app.services.booking_logic.maybe_create_booking to keep
        booking logic centralized and testable.
        """
        ctx = booking_logic.BookingCreationContext(
            business_id=self.business_id,
            business_name=self.business_name,
            business_config=self.business_config,
            caller_phone=self.caller_phone,
            call_id=self.call_id,
            conversation_history=self.conversation_history,
            preselected_service=self.booking_state.service,
        )
        return await booking_logic.maybe_create_booking(
            ctx=ctx,
            ai_response_text=ai_response_text,
            user_text=user_text,
            booking_already_created=self.booking_created,
        )


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
        Uses debouncing to prevent multiple rapid UtteranceEnd events from
        triggering multiple concurrent LLM calls (FIX #2).
        """
        self.is_user_speaking = False

        if self.current_transcript and self.current_transcript.strip():
            full_utterance = self.current_transcript.strip()
            self.current_transcript = ""  # Clear for next utterance

            print(f"🛑 Utterance detected: {full_utterance}")

            self.metrics.total_user_utterances += 1

            # Add to conversation history
            self.conversation_history.append({
                "role": "user",
                "content": full_utterance,
            })

            # Debounce: Cancel pending debounce task and create a new one
            # This ensures we only process once even if UtteranceEnd fires multiple times
            if self._utterance_debounce_task and not self._utterance_debounce_task.done():
                self._utterance_debounce_task.cancel()
                try:
                    await self._utterance_debounce_task
                except asyncio.CancelledError:
                    pass

            # Schedule processing with 500ms grace period
            # If another UtteranceEnd arrives before this, it cancels this task
            self._utterance_debounce_task = asyncio.create_task(
                self._debounced_process_utterance(full_utterance)
            )
        else:
            print(f"🛑 Utterance end (no transcript)")

    async def _debounced_process_utterance(self, utterance: str) -> None:
        """
        Process utterance after grace period, ensuring only one LLM call at a time.
        
        Args:
            utterance: The user's spoken text
        """
        try:
            # Grace period: wait a bit longer to see if the caller continues
            # the same thought. 800ms is a balance between responsiveness and
            # avoiding mid-sentence cut-offs.
            await asyncio.sleep(0.8)

            # If we've already scheduled the call to end, ignore any
            # further utterances to avoid reopening the conversation
            # after a clear goodbye / resolution.
            if self.pending_end_call:
                print("🛑 Ignoring utterance because call end is already scheduled")
                return

            # Acquire lock to ensure only one LLM processing happens at a time (FIX #1)
            async with self._processing_lock:
                print(f"🤖 Processing utterance (after debounce grace period): {utterance[:50]}...")
                await self._process_with_llm(utterance)

        except asyncio.CancelledError:
            print(f"🛑 Utterance debounce cancelled (user spoke again)")
            pass
        except Exception as e:
            print(f"❌ Error in debounced utterance processing: {e}")
            import traceback
            traceback.print_exc()

    async def _on_speech_started(self) -> None:
        """Handle start of user speech."""
        self.is_user_speaking = True

        # If a call end has already been scheduled (after a goodbye or
        # booking confirmation) but the caller starts speaking again,
        # treat this as a signal that they are not actually done.
        # Cancel the pending end so the conversation can continue.
        if self.pending_end_call:
            print("🛑 Speech detected after call end scheduled; cancelling pending end")
            self.pending_end_call = False
            if self._end_call_task and not self._end_call_task.done():
                self._end_call_task.cancel()
            # Fall through and allow normal barge-in handling below.

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
