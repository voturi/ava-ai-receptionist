from __future__ import annotations

from typing import TYPE_CHECKING, Optional, List

from app.services.workflows.base import Workflow, WorkflowResult

if TYPE_CHECKING:
    from app.services.call_session import CallSession
    from app.services.intent_detector import DetectedIntent


class AvailabilityWorkflow:
    """Workflow that answers generic availability questions.

    For now this is intentionally conservative and uses only the
    business's configured working_hours. It does not consult external
    calendars or guarantee real-time slot availability.

    Once calendar integration is available, this workflow can be
    extended to call a tool or provider to fetch actual free slots.
    """

    name = "availability"

    async def handle_turn(
        self,
        user_text: str,
        full_response: str,
        session: "CallSession",
        intent: "DetectedIntent",
        effective_intent: str,
    ) -> WorkflowResult:
        result = WorkflowResult()

        # Only consider running on information-style or booking-adjacent
        # turns; do not interfere with clear cancel/reschedule/emergency
        # flows.
        if intent.intent in {"cancel", "reschedule", "emergency"}:
            return result

        if not self._looks_like_availability_question(user_text):
            return result

        working_hours = (session.business_config or {}).get("working_hours") or {}
        if not working_hours:
            # No structured hours; respond generically without claiming
            # specific times.
            msg = (
                "We’re generally available during our normal business hours. "
                "If you tell me the day and a rough time that suits you, I can try to book it."
            )
            result.backend_messages.append(msg)
            return result

        # Build a concise summary from working_hours, similar to how
        # the system prompt does it.
        items: List[str] = []
        for day, hours in list(working_hours.items()):
            if not hours:
                continue
            label = str(day).capitalize()
            items.append(f"{label}: {hours}")
            if len(items) >= 5:
                break

        if not items:
            msg = (
                "We’re generally available during our normal business hours. "
                "If you tell me the day and time that suits you, I can help with a booking."
            )
        else:
            joined = ", ".join(items)
            msg = (
                f"Based on your saved hours, you’re usually open on these days: {joined}. "
                "Tell me which day and time you prefer, and I can help you book it."
            )

        result.backend_messages.append(msg)
        return result

    def _looks_like_availability_question(self, text: str) -> bool:
        t = (text or "").lower()
        if not t:
            return False

        keywords = [
            "are you available",
            "availability",
            "what time can you",
            "what time are you",
            "what times do you have",
            "time slots",
            "what time works",
            "when are you open",
            "when do you open",
            "when do you close",
            "when can you come",
            "when could you come",
        ]
        return any(k in t for k in keywords)
