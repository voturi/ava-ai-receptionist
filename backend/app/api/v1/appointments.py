from __future__ import annotations

import json
import os
from datetime import datetime, date, time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.db_service import DBService
from app.integrations.providers.base import BookingContext, CustomerInfo
from app.integrations.providers.registry import get_provider_config, resolve_provider
from app.integrations.twilio_client import twilio_client


router = APIRouter(tags=["appointments"])

PAYMENT_LINK_BASE_URL = os.getenv("PAYMENT_LINK_BASE_URL")


class _BaseToolArgs(BaseModel):
    """Common base for tool argument models.

    We keep this minimal and tolerant of extra fields coming from Vapi.
    """

    class Config:
        extra = "ignore"


class CheckAvailabilityArgs(_BaseToolArgs):
    business_id: str
    date: str
    service_type: Optional[str] = None


class BookAppointmentArgs(_BaseToolArgs):
    business_id: str
    customer_name: str
    customer_phone: str
    date: str
    time: str
    service_type: Optional[str] = None
    customer_email: Optional[str] = None


class RescheduleAppointmentArgs(_BaseToolArgs):
    business_id: str
    appointment_id: str
    new_date: str
    new_time: str


class CancelAppointmentArgs(_BaseToolArgs):
    business_id: str
    appointment_id: str
    reason: Optional[str] = None


class SendPaymentLinkArgs(_BaseToolArgs):
    business_id: str
    phone_number: str
    amount: Any
    appointment_id: str


def _extract_tool_arguments(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the first tool call's arguments from a Vapi tool payload.

    Expected shape (simplified):
    {
        "message": {
            "toolCallList": [
                {
                    "function": {
                        "name": "check_availability",
                        "arguments": { ... } or "{...}"  # JSON string
                    }
                }
            ]
        }
    }
    """

    message = payload.get("message") or {}
    tool_calls: List[Dict[str, Any]] = (
        message.get("toolCallList")
        or message.get("toolCalls")
        or []
    )

    if not tool_calls:
        raise HTTPException(status_code=400, detail="Missing toolCallList in request payload")

    function = (tool_calls[0] or {}).get("function") or {}
    args = function.get("arguments")

    # Vapi sometimes sends arguments as a JSON string
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in tool arguments")

    if not isinstance(args, dict):
        raise HTTPException(status_code=400, detail="Tool arguments must be an object")

    return args


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format; expected YYYY-MM-DD")


def _parse_time(value: str) -> time:
    # Support "HH:MM" and "HH:MM:SS" 24h formats
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail="Invalid time format; expected HH:MM (24h)")


def _combine_date_time(date_str: str, time_str: str) -> datetime:
    d = _parse_date(date_str)
    t = _parse_time(time_str)
    return datetime.combine(d, t)


async def _get_business_and_db_service(db: AsyncSession, business_id: str):
    db_service = DBService(db)
    business = await db_service.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return business, db_service


def _vapi_result(message: str, tool_call_id: Optional[str] = None) -> Dict[str, Any]:
    """Wrap a plain-text result in Vapi's expected response envelope.

    If a tool_call_id is provided, include it so Vapi can match the result to
    the originating tool call.
    """

    result: Dict[str, Any] = {"result": message}
    if tool_call_id:
        result["toolCallId"] = tool_call_id
    return {"results": [result]}


@router.post("/appointments/check-availability")
async def check_availability(request: Request, db: AsyncSession = Depends(get_db)):
    """Vapi tool endpoint: check availability for a given business & date.

    TEMP: hard-coded stub for Vapi contract testing.
    Original implementation is commented out below for later restore.
    """

    payload = await request.json()
    raw_args = _extract_tool_arguments(payload)
    args = CheckAvailabilityArgs(**raw_args)

    # Extract toolCallId so we can echo it back in the response
    message_envelope = payload.get("message") or {}
    tool_calls: List[Dict[str, Any]] = (
        message_envelope.get("toolCallList")
        or message_envelope.get("toolCalls")
        or []
    )
    tool_call_id = (tool_calls[0] or {}).get("id") if tool_calls else None

    # --- ORIGINAL IMPLEMENTATION (COMMENTED OUT) ---
    # business, _ = await _get_business_and_db_service(db, args.business_id)
    # requested_date = _parse_date(args.date)
    # provider_config = get_provider_config(business.ai_config)
    # provider = resolve_provider(provider_config)
    # context = BookingContext(
    #     business_id=args.business_id,
    #     business_name=business.name,
    #     service=args.service_type or "General",
    #     requested_datetime=datetime.combine(requested_date, time(hour=9, minute=0)),
    #     customer=CustomerInfo(name="Customer", phone=""),
    #     metadata=provider_config,
    # )
    # availability = await provider.check_availability(context)
    # if availability.available:
    #     message = (
    #         f"{business.name} appears to have availability on {requested_date.isoformat()}"
    #     )
    #     if availability.reason:
    #         message += f" – {availability.reason}"
    # else:
    #     message = (
    #         f"{business.name} is not available on {requested_date.isoformat()}"
    #     )
    #     if availability.reason:
    #         message += f" – {availability.reason}"

    # --- STUB RESPONSE ---
    message = (
        f"Stub: business {args.business_id} appears to have availability on "
        f"{args.date} for service {args.service_type or 'General'}."
    )

    return _vapi_result(message, tool_call_id)


@router.post("/appointments/book")
async def book_appointment(request: Request, db: AsyncSession = Depends(get_db)):
    """Vapi tool endpoint: book an appointment for a customer.

    This implementation creates a booking record in the primary Postgres
    database (Supabase) via DBService and sends an SMS confirmation via
    Twilio. External calendar availability checks (e.g. Google Calendar)
    can be layered in later.
    """

    payload = await request.json()
    raw_args = _extract_tool_arguments(payload)
    args = BookAppointmentArgs(**raw_args)

    # Extract toolCallId so we can echo it back in the response
    message_envelope = payload.get("message") or {}
    tool_calls: List[Dict[str, Any]] = (
        message_envelope.get("toolCallList")
        or message_envelope.get("toolCalls")
        or []
    )
    tool_call_id = (tool_calls[0] or {}).get("id") if tool_calls else None

    # Look up business + DB service for Supabase-backed persistence
    business, db_service = await _get_business_and_db_service(db, args.business_id)

    booking_datetime = _combine_date_time(args.date, args.time)

    # For now we skip external provider availability checks (Google Calendar
    # etc.) and simply create a confirmed booking. Calendar integration can
    # be added on top of this record later.
    booking_data = {
        "business_id": args.business_id,
        "call_id": None,
        "customer_name": args.customer_name,
        "customer_phone": args.customer_phone,
        "customer_email": args.customer_email,
        "service": args.service_type or "General",
        "booking_datetime": booking_datetime,
        "status": "confirmed",
        "confirmed_at": datetime.utcnow(),
        "internal_notes": "Created via Vapi /appointments/book tool",
        "customer_notes": None,
    }
    booking = await db_service.create_booking(booking_data)

    human_date = booking_datetime.strftime("%A %d %b %Y at %I:%M %p")
    message = (
        f"Booking confirmed with {business.name} for {human_date} "
        f"for {args.customer_name}. Booking ID: {booking.id}."
    )

    # Fire-and-forget SMS confirmation; failures shouldn't break the tool
    try:
        sms_body = (
            f"Hi {args.customer_name}, your booking with {business.name} is confirmed "
            f"for {human_date}. Booking ID: {booking.id}."
        )
        if business.twilio_number:
            twilio_client.send_sms(
                to=args.customer_phone,
                message=sms_body,
                from_=business.twilio_number,
            )
    except Exception:
        # Log at best-effort level; avoid raising into the tool path
        pass

    return _vapi_result(message, tool_call_id)


@router.post("/appointments/reschedule")
async def reschedule_appointment(request: Request, db: AsyncSession = Depends(get_db)):
    """Vapi tool endpoint: reschedule an existing appointment.

    TEMP: hard-coded stub for Vapi contract testing.
    Original implementation is commented out below for later restore.
    """

    payload = await request.json()
    raw_args = _extract_tool_arguments(payload)
    args = RescheduleAppointmentArgs(**raw_args)

    # Extract toolCallId so we can echo it back in the response
    message_envelope = payload.get("message") or {}
    tool_calls: List[Dict[str, Any]] = (
        message_envelope.get("toolCallList")
        or message_envelope.get("toolCalls")
        or []
    )
    tool_call_id = (tool_calls[0] or {}).get("id") if tool_calls else None

    # --- ORIGINAL IMPLEMENTATION (COMMENTED OUT) ---
    # business, db_service = await _get_business_and_db_service(db, args.business_id)
    # new_datetime = _combine_date_time(args.new_date, args.new_time)
    # booking = await db_service.get_booking(args.appointment_id)
    # if not booking or str(booking.business_id) != business.id.hex:
    #     raise HTTPException(status_code=404, detail="Appointment not found for this business")
    # updated = await db_service.update_booking(
    #     args.appointment_id,
    #     {
    #         "booking_datetime": new_datetime,
    #         "status": "confirmed",
    #     },
    # )
    # human_date = new_datetime.strftime("%A %d %b %Y at %I:%M %p")
    # message = (
    #     f"Appointment {updated.id} has been rescheduled with {business.name} "
    #     f"to {human_date}."
    # )

    # --- STUB RESPONSE ---
    new_datetime = _combine_date_time(args.new_date, args.new_time)
    human_date = new_datetime.strftime("%A %d %b %Y at %I:%M %p")
    message = (
        f"Stub: appointment {args.appointment_id} for business {args.business_id} "
        f"has been rescheduled to {human_date}."
    )

    return _vapi_result(message, tool_call_id)


@router.post("/appointments/cancel")
async def cancel_appointment(request: Request, db: AsyncSession = Depends(get_db)):
    """Vapi tool endpoint: cancel an existing appointment.

    TEMP: hard-coded stub for Vapi contract testing.
    Original implementation is commented out below for later restore.
    """

    payload = await request.json()
    raw_args = _extract_tool_arguments(payload)
    args = CancelAppointmentArgs(**raw_args)

    # Extract toolCallId so we can echo it back in the response
    message_envelope = payload.get("message") or {}
    tool_calls: List[Dict[str, Any]] = (
        message_envelope.get("toolCallList")
        or message_envelope.get("toolCalls")
        or []
    )
    tool_call_id = (tool_calls[0] or {}).get("id") if tool_calls else None

    # --- ORIGINAL IMPLEMENTATION (COMMENTED OUT) ---
    # business, db_service = await _get_business_and_db_service(db, args.business_id)
    # booking = await db_service.get_booking(args.appointment_id)
    # if not booking or str(booking.business_id) != business.id.hex:
    #     raise HTTPException(status_code=404, detail="Appointment not found for this business")
    # update_data: Dict[str, Any] = {"status": "cancelled"}
    # if args.reason:
    #     existing_notes = booking.internal_notes or ""
    #     reason_line = f"Cancelled via Vapi tool. Reason: {args.reason}"
    #     update_data["internal_notes"] = (
    #         f"{existing_notes}\n{reason_line}" if existing_notes else reason_line
    #     )
    # updated = await db_service.update_booking(args.appointment_id, update_data)
    # message = (
    #     f"Appointment {updated.id} with {business.name} has been cancelled."
    # )
    # if args.reason:
    #     message += f" Reason: {args.reason}."

    # --- STUB RESPONSE ---
    message = f"Stub: appointment {args.appointment_id} for business {args.business_id} has been cancelled."
    if args.reason:
        message += f" Reason: {args.reason}."

    return _vapi_result(message, tool_call_id)


@router.post("/sms/payment-link")
async def send_payment_link(request: Request, db: AsyncSession = Depends(get_db)):
    """Vapi tool endpoint: send an SMS payment link to the customer.

    TEMP: hard-coded stub for Vapi contract testing.
    Original implementation is commented out below for later restore.
    """

    payload = await request.json()
    raw_args = _extract_tool_arguments(payload)
    args = SendPaymentLinkArgs(**raw_args)

    # Extract toolCallId so we can echo it back in the response
    message_envelope = payload.get("message") or {}
    tool_calls: List[Dict[str, Any]] = (
        message_envelope.get("toolCallList")
        or message_envelope.get("toolCalls")
        or []
    )
    tool_call_id = (tool_calls[0] or {}).get("id") if tool_calls else None

    # --- ORIGINAL IMPLEMENTATION (COMMENTED OUT) ---
    # business, db_service = await _get_business_and_db_service(db, args.business_id)
    # try:
    #     amount = Decimal(str(args.amount))
    # except (InvalidOperation, TypeError):
    #     raise HTTPException(status_code=400, detail="Invalid amount value")
    # booking = await db_service.get_booking(args.appointment_id)
    # if not booking or str(booking.business_id) != business.id.hex:
    #     raise HTTPException(status_code=404, detail="Appointment not found for this business")
    # try:
    #     await db_service.update_booking(args.appointment_id, {"price": amount})
    # except Exception:
    #     pass
    # payment_url: Optional[str] = None
    # if PAYMENT_LINK_BASE_URL:
    #     base = PAYMENT_LINK_BASE_URL.rstrip("/")
    #     payment_url = f"{base}/{args.appointment_id}"
    # if payment_url:
    #     sms_body = (
    #         f"Hi, this is {business.name}. Please complete payment of ${amount} "
    #         f"for your appointment (ID: {args.appointment_id}) here: {payment_url}"
    #     )
    # else:
    #     sms_body = (
    #         f"Hi, this is {business.name}. Please complete payment of ${amount} "
    #         f"for your appointment (ID: {args.appointment_id})."
    #     )
    # twilio_client.send_sms(
    #     to=args.phone_number,
    #     message=sms_body,
    #     from_=business.twilio_number,
    # )
    # if payment_url:
    #     result_msg = (
    #         f"Payment link sent to {args.phone_number} for ${amount} "
    #         f"(appointment {args.appointment_id})."
    #     )
    # else:
    #     result_msg = (
    #         f"Payment SMS (without link URL) sent to {args.phone_number} for ${amount} "
    #         f"(appointment {args.appointment_id})."
    #     )

    # --- STUB RESPONSE ---
    try:
        amount = Decimal(str(args.amount))
    except (InvalidOperation, TypeError):
        raise HTTPException(status_code=400, detail="Invalid amount value")

    message = (
        f"Stub: payment link SMS would be sent to {args.phone_number} "
        f"for ${amount} for appointment {args.appointment_id} "
        f"for business {args.business_id}."
    )

    return _vapi_result(message, tool_call_id)
