from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.integrations.providers.base import BookingContext, CustomerInfo
from app.integrations.providers.registry import get_provider_config, resolve_provider
from app.core.database import AsyncSessionLocal
from app.services.db_service import DBService
from app.integrations.twilio_client import twilio_client


# ──────────────────────────────────────────────────────────────────────────────
# Name extraction helpers
# ──────────────────────────────────────────────────────────────────────────────


def clean_name_token(token: str) -> str:
    """Normalize a potential name token to a simple capitalized string."""
    cleaned = "".join(ch for ch in token if ch.isalpha())
    return cleaned.capitalize() if cleaned else ""


def extract_name(history: list[dict[str, Any]]) -> str:
    """Extract customer name from conversation history.

    More robust against punctuation and noisy ASR output.
    """
    for msg in reversed(history):
        if msg.get("role") != "user":
            continue

        content = msg.get("content", "").strip()
        if not content:
            continue

        content_lower = content.lower()

        # Helper: scan tokens after a marker phrase and return the first
        # token that cleans to a non-empty name.
        def _name_after(phrase: str) -> Optional[str]:
            idx = content_lower.find(phrase)
            if idx == -1:
                return None
            after = content[idx + len(phrase) :].strip()
            for raw in after.split():
                cleaned = clean_name_token(raw)
                if cleaned:
                    return cleaned
            return None

        # "my name is <Name>"
        name = _name_after("my name is")
        if name:
            return name

        # "this is <Name>"
        name = _name_after("this is")
        if name:
            return name

        # "and my <...>" patterns are tricky; in practice they tend to
        # appear as part of longer introductions. We keep a conservative
        # interpretation here.
        if " and my" in content_lower:
            before = content_lower.split(" and my")[0].strip()
            for raw in before.split():
                cleaned = clean_name_token(raw)
                if cleaned:
                    return cleaned

        # "I'm <Name>" / "I am <Name>"
        if "i'm" in content_lower or "i am" in content_lower:
            cleaned_text = content_lower.replace("i'm", "").replace("i am", "").strip()
            for raw in cleaned_text.split():
                cleaned = clean_name_token(raw)
                if cleaned:
                    return cleaned

        # Fallback: if the reply itself looks like just a name (1-2 words,
        # no digits), treat the first token as the name.
        words = [w for w in content.split() if any(ch.isalpha() for ch in w)]
        if words and len(words) <= 2 and not any(ch.isdigit() for ch in content):
            cleaned_name = clean_name_token(words[0])
            if cleaned_name:
                return cleaned_name

    return "Customer"


# ──────────────────────────────────────────────────────────────────────────────
# Datetime extraction helpers
# ──────────────────────────────────────────────────────────────────────────────


def local_now() -> datetime:
    """Return current time in Australia/Sydney as naive local time.

    Matches CallSession._local_now behaviour.
    """
    local = datetime.now(ZoneInfo("Australia/Sydney"))
    return local.replace(tzinfo=None)


def extract_datetime_from_history(history: list[dict[str, Any]]) -> Optional[datetime]:
    """Extract a requested datetime from conversation history (most recent first).

    Ported from CallSession._extract_datetime_from_history.
    """
    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }

    time_pattern = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.IGNORECASE)

    for msg in reversed(history):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        content_lower = content.lower()

        day: Optional[int] = None
        for name, idx in weekdays.items():
            if name in content_lower:
                day = idx
                break

        time_match = time_pattern.search(content_lower)
        if day is None and not time_match:
            continue

        now = local_now()
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


def extract_datetime_from_text(text: str) -> Optional[datetime]:
    """Extract a requested datetime from a single text snippet.

    Ported from CallSession._extract_datetime_from_text.
    """
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
    time_pattern = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.IGNORECASE)

    day: Optional[int] = None
    for name, idx in weekdays.items():
        if name in content_lower:
            day = idx
            break

    time_match = time_pattern.search(content_lower)

    if day is None and not time_match and "tomorrow" not in content_lower:
        return None

    now = local_now()
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


# ──────────────────────────────────────────────────────────────────────────────
# Service & issue extraction
# ──────────────────────────────────────────────────────────────────────────────


def extract_service_from_history(services: list[Any], history: list[dict[str, Any]]) -> Optional[str]:
    """Find a matching service name from conversation history.

    Ported from CallSession._extract_service_from_history.
    """
    if not services:
        return None

    history_text = " ".join(msg.get("content", "").lower() for msg in history)

    for service in services:
        if isinstance(service, dict):
            name = str(service.get("name", "")).lower()
        else:
            name = str(service).lower()
        if name and name in history_text:
            return str(service.get("name")) if isinstance(service, dict) else str(service)

    return None


def extract_issue_summary(history: list[dict[str, Any]]) -> Optional[str]:
    """Return the most recent user utterance as issue summary.

    Ported from CallSession._extract_issue_summary.
    """
    for msg in reversed(history):
        if msg.get("role") == "user":
            content = msg.get("content", "").strip()
            return content[:500] if content else None
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Booking confirmation heuristics
# ──────────────────────────────────────────────────────────────────────────────


def response_sounds_confirmed(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    confirmation_signals = [
        "confirmed",
        "all set",
        "you're all set",
        "appointment is set",
        "booked",
        "i've booked",
        "i have booked",
        "reserved",
        "your appointment is confirmed",
        "your booking is confirmed",
    ]
    return any(signal in lower for signal in confirmation_signals)


def user_confirms_booking(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    confirmation_signals = [
        "yes",
        "yep",
        "yeah",
        "correct",
        "that's correct",
        "that is correct",
        "right",
        "sounds good",
        "that's fine",
        "that works",
        "please book",
        "go ahead",
        "book it",
        "confirm",
        "please confirm",
        "sure",
    ]
    return any(signal in lower for signal in confirmation_signals)


def response_requests_finalization(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    finalization_signals = [
        "shall i go ahead",
        "go ahead and finalise",
        "finalize",
        "finalise",
        "confirm that booking",
        "go ahead and book",
        "should i book",
        "should i confirm",
        "can i confirm",
        "want me to book",
        "want me to confirm",
        "ready to book",
    ]
    return any(signal in lower for signal in finalization_signals)


def get_missing_booking_prompt(
    *,
    services: list[Any],  # kept for signature compatibility; no longer required
    history: list[dict[str, Any]],
    ai_response_text: str,
    caller_phone: str,
) -> str:
    """Generate a follow-up question when AI sounded confirmed but booking not created.

    We no longer block bookings on a strict catalog service match. This
    helper focuses only on genuinely missing *essential* fields:
    - datetime
    - customer name
    - customer phone
    """
    requested_dt = extract_datetime_from_history(history)
    if requested_dt is None and ai_response_text:
        requested_dt = extract_datetime_from_text(ai_response_text)

    customer_name = extract_name(history)

    if not requested_dt:
        return "Before I can confirm, what day and time works best?"
    if customer_name == "Customer" or not customer_name:
        return "Before I can confirm, could I grab your name?"
    if not caller_phone:
        return "Before I can confirm, what's the best mobile number for confirmation?"

    return "I couldn't confirm that just yet. What time would work instead?"


def is_booking_complete(
    *,
    collected_data: dict,
    history: list[dict[str, Any]],
    caller_phone: Optional[str],
    ai_response_text: str,
) -> bool:
    """Determine whether we have enough info to safely create a booking.

    Ported from CallSession._is_booking_complete.
    """
    completion_signals = [
        "all set",
        "i'll sms you",
        "i will sms",
        "sms you soon",
        "confirmed",
        "booked",
        "appointment is set",
        "you're all set",
        "everything is confirmed",
        "i'll book",
        "i will book",
        "i'll schedule",
        "i will schedule",
        "thanks for confirming",
    ]
    ai_text_lower = ai_response_text.lower()
    has_completion_signal = any(signal in ai_text_lower for signal in completion_signals)
    if not has_completion_signal:
        return False

    has_service = "service" in collected_data and collected_data["service"]
    has_name = extract_name(history) != "Customer"
    has_phone = bool(caller_phone)
    has_datetime = (
        extract_datetime_from_history(history) is not None
        or extract_datetime_from_text(ai_response_text) is not None
    )

    # For safety, a booking is considered complete when we have:
    # - a datetime,
    # - a real customer name,
    # - a phone number.
    # Service/category is advisory and should not block booking.
    if has_name and has_phone and has_datetime:
        return True

    print(
        f"🔎 Booking incomplete: service={has_service} name={has_name} "
        f"phone={has_phone} datetime={has_datetime}"
    )
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Booking creation
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class BookingCreationContext:
    business_id: str
    business_name: str
    business_config: dict
    caller_phone: Optional[str]
    call_id: Optional[str]
    conversation_history: list[dict[str, Any]]
    preselected_service: Optional[str] = None


async def maybe_create_booking(
    *,
    ctx: BookingCreationContext,
    ai_response_text: str,
    user_text: Optional[str],
    booking_already_created: bool,
) -> dict:
    """Create a booking if conversation indicates completion and data is sufficient.

    This is a functional extraction of CallSession._maybe_create_booking.
    Returns a dict: {"created": bool, "confirmation_text": Optional[str], "booking_id": Optional[str]}.
    """
    if booking_already_created:
        return {"created": True, "confirmation_text": None, "booking_id": None}

    if not ctx.call_id:
        return {"created": False, "confirmation_text": None, "booking_id": None}

    if not user_confirms_booking(user_text or ""):
        print("🔎 Booking blocked: waiting_for_user_confirmation")
        return {"created": False, "confirmation_text": None, "booking_id": None}

    services = ctx.business_config.get("services") or []
    service = ctx.preselected_service or extract_service_from_history(
        services, ctx.conversation_history
    )
    requested_dt = extract_datetime_from_history(ctx.conversation_history)
    if requested_dt is None and ai_response_text:
        requested_dt = extract_datetime_from_text(ai_response_text)

    customer_name = extract_name(ctx.conversation_history)
    customer_phone = ctx.caller_phone or ""

    if customer_name == "Customer" or not customer_phone:
        print(
            "🔎 Booking blocked: missing_name_or_phone "
            f"name={'ok' if customer_name != 'Customer' else 'missing'} "
            f"phone={'ok' if customer_phone else 'missing'}"
        )
        return {"created": False, "confirmation_text": None, "booking_id": None}

    has_datetime = requested_dt is not None
    if not has_datetime:
        print(
            "🔎 Booking blocked: missing_datetime "
            f"datetime={'ok' if has_datetime else 'missing'}"
        )
        return {"created": False, "confirmation_text": None, "booking_id": None}

    # Service/category is best-effort. If we couldn't reliably map it to a
    # configured service, fall back to a sensible generic label; the
    # detailed issue is still captured in customer_notes.
    if not service:
        service = extract_issue_summary(ctx.conversation_history) or "General"

    provider_config = get_provider_config(ctx.business_config.get("ai_config"))
    provider = resolve_provider(provider_config)
    context = BookingContext(
        business_id=ctx.business_id,
        business_name=ctx.business_name,
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
        print("🔎 Booking blocked: provider_unavailable")
        return {"created": False, "confirmation_text": None, "booking_id": None}

    intent = await provider.create_booking(context)
    if intent.status == "declined":
        print("🔎 Booking blocked: provider_declined")
        return {"created": False, "confirmation_text": None, "booking_id": None}

    booking_datetime = requested_dt or local_now()
    internal_notes = None
    if intent.external_reference:
        internal_notes = f"Provider reference: {intent.external_reference}"

    async with AsyncSessionLocal() as session:
        db_service = DBService(session)
        booking = await db_service.create_booking(
            {
                "business_id": ctx.business_id,
                "call_id": ctx.call_id,
                "customer_name": customer_name,
                "customer_phone": customer_phone,
                "service": service or "General",
                "booking_datetime": booking_datetime,
                "status": intent.status,
                "confirmed_at": datetime.utcnow()
                if intent.status == "confirmed"
                else None,
                "internal_notes": internal_notes,
                "customer_notes": extract_issue_summary(ctx.conversation_history),
            }
        )

    try:
        booking_date = booking_datetime.strftime("%A %d %b %Y at %I:%M %p")
        sms_message = (
            f"Hi {customer_name}! Your {service or 'service'} appointment at "
            f"{ctx.business_name} is confirmed for {booking_date}."
        )
        if intent.message_override:
            sms_message = intent.message_override
        twilio_client.send_sms(
            customer_phone,
            sms_message,
            from_=ctx.business_config.get("twilio_number"),
        )
    except Exception as e:  # pragma: no cover - defensive logging
        print(f"❌ ERROR sending SMS: {e}")

    print(f"✅ BOOKING CREATED: {booking.id} ({customer_name}, {service})")
    confirmation_text = (
        f"Your appointment is confirmed for {booking_date}. "
        f"You'll receive a confirmation message shortly."
    )
    return {
        "created": True,
        "confirmation_text": confirmation_text,
        "booking_id": str(booking.id),
    }
