from datetime import datetime

from fastapi import APIRouter, Request, Response, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.twiml.messaging_response import MessagingResponse

from app.core.database import get_db
from app.services.db_service import DBService

router = APIRouter()


@router.post("/incoming")
async def handle_incoming_sms(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Twilio webhook for inbound SMS."""
    form = await request.form()
    from_number = form.get("From")
    to_number = form.get("To")
    body = (form.get("Body") or "").strip()
    message_sid = form.get("MessageSid")

    print(f"""
    ═══════════════════════════════════════
    📩 NEW SMS
    ═══════════════════════════════════════
    From: {from_number}
    To: {to_number}
    Message SID: {message_sid}
    Time: {datetime.now().strftime('%H:%M:%S')}
    Body: {body}
    ═══════════════════════════════════════
    """)

    db_service = DBService(db)
    business = await db_service.get_business_by_phone(to_number) if to_number else None
    business_name = business.name if business else "our business"

    response = MessagingResponse()
    response.message(
        f"Thanks for your message! {business_name} will get back to you shortly."
    )
    return Response(content=str(response), media_type="application/xml")
