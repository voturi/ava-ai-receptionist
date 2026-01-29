from __future__ import annotations

# NOTE: AvailabilityWorkflow has been disabled in favour of relying on
# ai_config/system-prompt driven behaviour for working hours. This file
# is kept as a stub for potential future use.

from typing import TYPE_CHECKING, Optional, List

from app.services.workflows.base import Workflow, WorkflowResult

if TYPE_CHECKING:
    from app.services.call_session import CallSession
    from app.services.intent_detector import DetectedIntent


class AvailabilityWorkflow:
    """(Disabled) Availability workflow.

    Previously this attempted to answer generic availability questions
    by reading structured working_hours from the DB and constructing a
    spoken summary. For now, this behaviour has been turned off to
    return to the original, LLM/ai_config-driven handling of business
    hours.
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
        # No-op: rely on the main LLM/system prompt instead.
        return WorkflowResult()

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
