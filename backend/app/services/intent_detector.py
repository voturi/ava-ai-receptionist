from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Any

from app.services.intent_profiles import IssueIntentProfile, match_issue_intent


IntentType = Literal["booking", "cancel", "reschedule", "info", "emergency", "other"]


@dataclass
class DetectedIntent:
    """Lightweight intent classification result for a single utterance.

    "intent" remains the high-level, workflow-driving label used
    throughout the codebase (booking/cancel/reschedule/info/emergency/other).
    Additional fields expose a richer, domain-specific issue intent that is
    loaded from the plumbing intent mapping CSV.
    """

    # High-level intent used for workflows and conversation_mode
    intent: IntentType

    # Confidence score for the high-level label (0–1)
    confidence: float

    # Short machine-readable reason / source of the decision
    reason: str

    # Optional domain-specific issue intent, mapped from the CSV
    issue_id: Optional[str] = None
    issue_confidence: float = 0.0
    issue_profile: Optional[IssueIntentProfile] = None

    # Optional debug payload for logging / inspection
    debug: Optional[dict[str, Any]] = None


def detect_intent(user_text: str, history: Optional[list[dict[str, Any]]] = None) -> DetectedIntent:
    """Rule-based intent detection for voice calls.

    This is intentionally simple and fast. It now has two layers:

    - a cheap, rule-based high-level classifier (booking/cancel/etc.) used
      for workflows and conversation control.
    - a CSV-backed domain issue matcher that maps the utterance to one of
      the configured plumbing workflows where possible.
    """

    text = (user_text or "").lower()

    # Keyword buckets (overlapping is allowed; we'll apply priorities)
    booking_kw = ["book", "booking", "appointment", "schedule", "reserve"]
    cancel_kw = ["cancel", "cancellation", "call it off", "can't make it"]
    resched_kw = ["reschedule", "move my booking", "change my booking", "change the time", "different time"]
    emergency_kw = [
        "burst pipe",
        "flood",
        "flooding",
        "smell gas",
        "gas leak",
        "no power",
        "power outage",
        "emergency",
    ]
    info_kw = ["price", "cost", "how much", "quote", "hours", "open", "close", "location", "where are you"]

    def any_kw(kws: list[str]) -> bool:
        return any(kw in text for kw in kws)

    scores: dict[IntentType, float] = {
        "booking": 0.0,
        "cancel": 0.0,
        "reschedule": 0.0,
        "info": 0.0,
        "emergency": 0.0,
        "other": 0.0,
    }

    if any_kw(booking_kw):
        scores["booking"] = 0.8
    if any_kw(cancel_kw):
        scores["cancel"] = 0.9
    if any_kw(resched_kw):
        scores["reschedule"] = 0.9
    if any_kw(info_kw):
        scores["info"] = max(scores["info"], 0.7)
    if any_kw(emergency_kw):
        scores["emergency"] = 1.0

    # Fallback: if text is very short / generic, treat as info/other
    if len(text.split()) <= 3 and not any(v > 0 for v in scores.values()):
        scores["info"] = 0.4

    # Pick highest score with fixed priority order (emergency first etc.)
    priority: list[IntentType] = [
        "emergency",
        "cancel",
        "reschedule",
        "booking",
        "info",
        "other",
    ]

    best_intent: IntentType = "other"
    best_score = 0.0
    for label in priority:
        score = scores.get(label, 0.0)
        if score > best_score:
            best_score = score
            best_intent = label

    if best_score == 0.0:
        best_intent = "other"

    # Domain-level issue matching using the CSV mapping.
    issue_profile, issue_confidence = match_issue_intent(user_text or "")

    reason = f"rule_match:{best_intent}" if best_score > 0 else "no_match"

    debug_payload: dict[str, Any] = {"scores": scores}
    if issue_profile is not None:
        debug_payload["issue_id"] = issue_profile.id
        debug_payload["issue_confidence"] = issue_confidence

    return DetectedIntent(
        intent=best_intent,
        confidence=best_score,
        reason=reason,
        issue_id=issue_profile.id if issue_profile else None,
        issue_confidence=issue_confidence,
        issue_profile=issue_profile,
        debug=debug_payload or None,
    )
