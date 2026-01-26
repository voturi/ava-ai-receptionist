from __future__ import annotations

from typing import TYPE_CHECKING

from app.services import booking_logic
from app.services.streaming_ai_service import streaming_ai_service
from app.services.workflows.base import Workflow, WorkflowResult

if TYPE_CHECKING:
    from app.services.call_session import CallSession
    from app.services.intent_detector import DetectedIntent


class BookingWorkflow:
    """Workflow for handling booking-specific logic after each turn.

    This wraps the existing behaviour that lived in ConversationEngine
    after the streaming LLM response:
    - Detects when to attempt booking creation.
    - Invokes booking_logic.maybe_create_booking.
    - Emits backend-driven correction prompts when the LLM sounded
      confirmed but booking was not actually created.

    Over time this can evolve to use a structured BookingState, but for
    now it mirrors the current semantics using CallSession fields.
    """

    name = "booking"

    async def handle_turn(
        self,
        user_text: str,
        full_response: str,
        session: "CallSession",
        intent: "DetectedIntent",
        effective_intent: str,
    ) -> WorkflowResult:
        result = WorkflowResult()

        # Only run booking behaviour when the effective workflow is booking
        if effective_intent != "booking":
            return result

        booking_result: dict = {"created": False, "confirmation_text": None, "booking_id": None}
        booking_created: bool = False
        confirmation_text: str | None = None

        # Attempt booking creation only after we explicitly asked to finalize.
        asks_finalization = booking_logic.response_requests_finalization(full_response)
        if asks_finalization:
            session.awaiting_final_confirmation = True

        # Opportunistically populate structured booking_state fields
        # from the accumulated conversation history and latest model
        # response. This does not yet drive behaviour but prepares for
        # future refactors.
        services = session.business_config.get("services") or []
        bs = session.booking_state
        if not bs.service:
            bs.service = booking_logic.extract_service_from_history(
                services, session.conversation_history
            )

        # If heuristics did not find a service, fall back to a lightweight
        # LLM-based classifier that maps the caller's issue description to
        # one of the configured services.
        if not bs.service and services:
            user_utterances = [
                msg.get("content", "")
                for msg in session.conversation_history
                if msg.get("role") == "user"
            ]
            user_utterances = [u for u in user_utterances if u.strip()]
            if user_utterances:
                try:
                    # Use a broader slice of user utterances so the
                    # classifier can see the original problem description,
                    # not just the last couple of booking confirmations.
                    mapped_service = await streaming_ai_service.classify_service(
                        user_utterances=user_utterances[-12:],
                        services=services,
                        business_name=session.business_name,
                        industry=session.business_config.get("industry"),
                    )
                    if mapped_service:
                        print(f"🧭 LLM mapped issue to service: {mapped_service}")
                        bs.service = mapped_service
                except Exception as e:  # pragma: no cover - defensive logging
                    print(f"⚠️ Service classification failed: {e}")

        if not bs.when:
            when = booking_logic.extract_datetime_from_history(session.conversation_history)
            if not when and full_response:
                when = booking_logic.extract_datetime_from_text(full_response)
            bs.when = when
        if not bs.name:
            bs.name = booking_logic.extract_name(session.conversation_history)
        if not bs.phone:
            bs.phone = session.caller_phone

        if session.awaiting_final_confirmation and booking_logic.user_confirms_booking(user_text or ""):
            ctx = booking_logic.BookingCreationContext(
                business_id=session.business_id,
                business_name=session.business_name,
                business_config=session.business_config,
                caller_phone=session.caller_phone,
                call_id=session.call_id,
                conversation_history=session.conversation_history,
                preselected_service=session.booking_state.service,
            )
            booking_result = await booking_logic.maybe_create_booking(
                ctx=ctx,
                ai_response_text=full_response,
                user_text=user_text,
                booking_already_created=session.booking_created,
            )

        booking_created = bool(booking_result.get("created", False))
        if booking_created:
            session.booking_created = True
            session.awaiting_final_confirmation = False
            result.state_changed = True
            # Update structured booking_state if available
            booking_id = booking_result.get("booking_id")
            if booking_id:
                session.booking_state.booking_id = booking_id
            session.booking_state.confirmed = True

        confirmation_text = booking_result.get("confirmation_text")

        # If AI sounded like it confirmed but booking was not created,
        # correct course with a backend-driven clarification.
        if (
            not booking_created
            and not asks_finalization
            and booking_logic.response_sounds_confirmed(full_response)
            and booking_logic.user_confirms_booking(user_text or "")
        ):
            prompt = booking_logic.get_missing_booking_prompt(
                services=session.business_config.get("services") or [],
                history=session.conversation_history,
                ai_response_text=full_response,
                caller_phone=session.caller_phone or "",
            )
            result.backend_messages.append(prompt)

        # If booking was created but the LLM response itself did not
        # sound confirmed, we can optionally emit a concise backend
        # confirmation message.
        if (
            booking_created
            and confirmation_text
            and not booking_logic.response_sounds_confirmed(full_response)
        ):
            result.backend_messages.append(confirmation_text)

        return result
