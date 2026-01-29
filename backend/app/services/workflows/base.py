from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.call_session import CallSession
    from app.services.intent_detector import DetectedIntent


@dataclass
class WorkflowResult:
    """Result of handling a single conversational turn in a workflow.

    - should_end_call: workflow considers the interaction complete
    - state_changed: booking or other session state was updated
    - backend_messages: extra messages the backend wants to speak
      (e.g. confirmations or clarifications) in addition to the LLM
      streaming output that has already been sent.
    """

    should_end_call: bool = False
    state_changed: bool = False
    backend_messages: List[str] = field(default_factory=list)


class Workflow(Protocol):
    """Interface for intent-specific workflows (booking, info, etc.)."""

    name: str

    async def handle_turn(
        self,
        user_text: str,
        full_response: str,
        session: "CallSession",
        intent: "DetectedIntent",
        effective_intent: str,
    ) -> WorkflowResult:
        ...
