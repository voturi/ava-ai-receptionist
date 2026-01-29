from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, TYPE_CHECKING

from app.services import booking_logic
from app.services.intent_detector import DetectedIntent, detect_intent
from app.services.streaming_ai_service import streaming_ai_service
from app.services.workflows import (
    BookingWorkflow,
    InfoPolicyWorkflow,
    AvailabilityWorkflow,
    WorkflowResult,
)
from app.tools.tool_definitions import TOOLS

if TYPE_CHECKING:
    from app.services.call_session import CallSession


@dataclass
class ConversationEngineConfig:
    """Configuration and shared state for a conversation turn.

    This wraps the pieces of CallSession that the engine needs without
    re-owning transport (STT/TTS/Twilio). The CallSession remains in
    charge of audio I/O and metrics; the engine focuses on:

    - Streaming LLM + tools
    - Booking decisions
    - End-of-call suggestion
    """

    session: "CallSession"


class ConversationEngine:
    """Encapsulate the LLM + tools + booking pipeline for a single utterance.

    This is effectively a refactor of CallSession._process_with_llm.
    """

    def __init__(self, config: ConversationEngineConfig) -> None:
        self.session = config.session

    async def process_utterance(self, user_text: str) -> None:
        """Run the full LLM → tools → booking decision flow for an utterance.

        This method is a behaviour-preserving extraction of
        CallSession._process_with_llm. It assumes the caller has already
        validated that TTS is connected and will handle any outer
        exception reporting.
        """
        session = self.session

        if not session.tts_connection or not session.tts_connection.is_connected:
            print("⚠️ TTS not connected, skipping LLM processing")
            return

        print(f"🤖 Processing with LLM: {user_text[:50]}...")

        # Detect high-level intent for this utterance
        intent: DetectedIntent = detect_intent(user_text, session.conversation_history)
        session.last_intent = intent.intent

        # Update sticky primary intent/workflow. Once we enter booking,
        # we stay there unless a stronger primary (cancel / reschedule /
        # emergency) is detected.
        if session.primary_intent is None:
            if intent.intent == "booking":
                session.primary_intent = "booking"
        elif session.primary_intent == "booking":
            if intent.intent in {"cancel", "reschedule", "emergency"}:
                session.primary_intent = intent.intent

        effective_intent = session.primary_intent or intent.intent
        issue_part = (
            f", issue_id={intent.issue_id} (issue_conf={intent.issue_confidence:.2f})"
            if getattr(intent, "issue_id", None)
            else ""
        )
        print(
            f"🧭 Detected intent: {intent.intent} (conf={intent.confidence:.2f})"  # high-level
            f"{issue_part}, primary={session.primary_intent or '-'}, effective={effective_intent}"
        )

        # LLM conversation mode is per-utterance and slightly different from
        # the sticky primary intent used for workflows. For this turn:
        # - if the user explicitly sounds like booking, use "booking" mode
        # - if the user clearly sounds like an emergency, use a dedicated
        #   emergency mode to tighten safety instructions.
        # - otherwise, treat as information/triage so we don't over-push
        #   booking details while answering questions.
        if intent.intent == "booking":
            llm_conversation_mode = "booking"
        elif intent.intent == "emergency":
            llm_conversation_mode = "emergency_info"
        else:
            llm_conversation_mode = "info"

        # Track timing
        llm_start = datetime.utcnow()
        first_token_received = False
        full_response = ""

        prefetched_tools = await session._prefetch_tools(user_text)  # noqa: SLF001

        try:
            # Stream LLM response with tools (mid-stream tool calling)
            buffer = ""
            async for event in streaming_ai_service.stream_with_tools(
                user_message=user_text,
                conversation_history=session.conversation_history[:-1],
                business_profile=session._get_business_profile(),  # noqa: SLF001
                tools=TOOLS,
                tool_executor=session._execute_tool,  # noqa: SLF001
                max_tool_calls=2,
                prefetched_tools=prefetched_tools,
                conversation_mode=llm_conversation_mode,
                intent=intent,
            ):
                if event.get("type") == "tool_call":
                    session.tool_history.append(event)
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

                if streaming_ai_service._should_yield(buffer, min_size=10):  # noqa: SLF001
                    await session.tts_connection.send_text(buffer)
                    buffer = ""

            if buffer:
                await session.tts_connection.send_text(buffer)

            # Signal end of text to TTS
            await session.tts_connection.flush()

            # Add AI response to conversation history
            if full_response:
                session.conversation_history.append(
                    {
                        "role": "assistant",
                        "content": full_response,
                    }
                )

            total_latency = (datetime.utcnow() - llm_start).total_seconds() * 1000
            print(f"🤖 AI Response ({total_latency:.0f}ms): {full_response}")

            # First, run info/policy workflow to enrich LLM answers
            # with ground-truth data from policies/FAQs when relevant.
            info_workflow = InfoPolicyWorkflow()
            info_result: WorkflowResult = await info_workflow.handle_turn(
                user_text=user_text,
                full_response=full_response,
                session=session,
                intent=intent,
                effective_intent=effective_intent,
            )

            # Then run availability workflow for generic availability
            # questions based on working_hours.
            availability_workflow = AvailabilityWorkflow()
            availability_result: WorkflowResult = await availability_workflow.handle_turn(
                user_text=user_text,
                full_response=full_response,
                session=session,
                intent=intent,
                effective_intent=effective_intent,
            )

            # Then run booking workflow (or no-op if effective intent is not booking)
            booking_workflow = BookingWorkflow()
            booking_result: WorkflowResult = await booking_workflow.handle_turn(
                user_text=user_text,
                full_response=full_response,
                session=session,
                intent=intent,
                effective_intent=effective_intent,
            )

            # Speak any backend-driven messages (e.g. corrections,
            # confirmations, or policy/availability info) after the
            # streamed LLM output.
            for msg in (
                info_result.backend_messages
                + availability_result.backend_messages
                + booking_result.backend_messages
            ):
                await session.speak(msg)

            # Update call record with transcript after workflow updates
            await session._update_call_record()  # noqa: SLF001

            # Check if we should end the call
            # Use current booking_created state (which may have been
            # updated by the workflow) when deciding to close.
            if session._should_end_call(user_text, full_response, session.booking_created):  # noqa: SLF001
                print("📞 Scheduling call end after TTS completes...")
                # Don't wait for marks in streaming mode - end call soon after final TTS
                session.pending_end_call = True
                if session._end_call_task and not session._end_call_task.done():  # noqa: SLF001
                    session._end_call_task.cancel()
                # Shorter timeout - just enough for TTS to send final audio
                session._end_call_task = asyncio.create_task(  # noqa: SLF001
                    session._end_call_timeout(timeout_seconds=2)  # noqa: SLF001
                )

        except Exception as e:  # pragma: no cover - defensive logging
            print(f"❌ LLM processing error: {e}")
            # Fallback: speak an error message
            await session.speak("Sorry, I'm having trouble right now. Can you say that again?")
