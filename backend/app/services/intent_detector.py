from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Any


IntentType = Literal["booking", "cancel", "reschedule", "info", "emergency", "other"]


@dataclass
class DetectedIntent:
    """Lightweight intent classification result for a single utterance."""

    intent: IntentType
    confidence: float
    reason: str
    debug: Optional[dict[str, Any]] = None


def detect_intent(user_text: str, history: Optional[list[dict[str, Any]]] = None) -> DetectedIntent:
    """Rule-based intent detection for voice calls.

    This is intentionally simple and fast. It can be upgraded later to
    a model-based classifier without changing the public shape.
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

    reason = f"rule_match:{best_intent}" if best_score > 0 else "no_match"

    return DetectedIntent(
        intent=best_intent,
        confidence=best_score,
        reason=reason,
        debug={"scores": scores} if scores else None,
    )
