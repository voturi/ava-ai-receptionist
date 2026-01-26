from __future__ import annotations

from typing import TYPE_CHECKING, Optional, List

from app.core.database import AsyncSessionLocal
from app.services.db_service import DBService
from app.services.workflows.base import Workflow, WorkflowResult

if TYPE_CHECKING:
    from app.services.call_session import CallSession
    from app.services.intent_detector import DetectedIntent


class InfoPolicyWorkflow:
    """Workflow that answers business policy / FAQ style questions.

    This workflow is designed to run in addition to the LLM streaming
    response and to inject ground-truth information from the Policy and
    FAQ tables. It is intentionally conservative: if it cannot detect a
    clear policy topic in the utterance, it is a no-op.
    """

    name = "info_policy"

    async def handle_turn(
        self,
        user_text: str,
        full_response: str,
        session: "CallSession",
        intent: "DetectedIntent",
        effective_intent: str,
    ) -> WorkflowResult:
        result = WorkflowResult()

        # Only consider running on information-style intents; for now we
        # piggyback on the generic "info" intent and further narrow to
        # policy-related questions.
        if intent.intent not in {"info", "other"}:
            return result

        topic_hint = self._infer_topic(user_text)
        if topic_hint is None:
            # Not obviously a policy/FAQ question; skip.
            return result

        # Look up policies/FAQs for this business.
        policies, faqs = await self._fetch_policy_and_faqs(session.business_id, topic_hint)

        if not policies and not faqs:
            # No structured info stored; do not override LLM, just skip.
            return result

        # Build a concise, backend-driven summary to append after the
        # LLM's answer.
        lines: List[str] = []
        if policies:
            lines.append("Here are some details from your saved policies:")
            for p in policies[:3]:
                snippet = (p.content or "").strip()
                if len(snippet) > 180:
                    snippet = snippet[:177] + "..."
                lines.append(f"- {p.topic.replace('_', ' ').title()}: {snippet}")

        if faqs:
            lines.append("Common questions we have on file:")
            for f in faqs[:2]:
                q = (f.question or "").strip()
                a = (f.answer or "").strip()
                if len(a) > 160:
                    a = a[:157] + "..."
                lines.append(f"- Q: {q} A: {a}")

        result.backend_messages.append("\n".join(lines))
        return result

    def _infer_topic(self, text: str) -> Optional[str]:
        """Infer a high-level policy/FAQ topic from the user utterance.

        This is a simple rule-based mapper; DBService will further
        normalise topics (e.g. call_out_fee vs callout_fee).
        """
        t = text.lower()

        # Cancellation / refunds / deposits
        if any(k in t for k in ["cancel", "cancellation", "cancelled", "cancelling"]):
            return "cancellation"
        if "refund" in t:
            return "refunds"
        if "deposit" in t:
            return "deposit"

        # Pricing / call-out / after hours
        if any(k in t for k in ["price", "pricing", "cost", "how much", "quote"]):
            return "pricing"
        if any(k in t for k in ["call out", "call-out", "callout"]):
            return "call_out_fee"
        if any(k in t for k in ["after hours", "after-hours", "afterhours"]):
            return "after_hours"

        # Parking / access / location
        if "parking" in t:
            return "parking"
        if any(k in t for k in ["access", "gate code", "entry code"]):
            return "access"

        # Generic policy keyword
        if "policy" in t or "policies" in t:
            return None  # let DBService return recent policies with no topic

        return None

    async def _fetch_policy_and_faqs(self, business_id: str, topic: Optional[str]):
        async with AsyncSessionLocal() as db_sess:
            db = DBService(db_sess)
            policies = await db.get_policies(business_id, topic=topic, limit=5)
            faqs = await db.get_faqs(business_id, topic=topic, limit=5)
        return policies, faqs
