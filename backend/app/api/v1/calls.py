from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.services.db_service import DBService
from typing import List
import uuid

router = APIRouter()

@router.get("/{business_id}/calls")
async def get_business_calls(
    business_id: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """Get recent calls for a business"""
    db_service = DBService(db)
    calls = await db_service.get_business_calls(business_id, limit)
    
    return {
        "business_id": business_id,
        "total": len(calls),
        "calls": [
            {
                "id": str(call.id),
                "caller_phone": call.caller_phone,
                "started_at": call.started_at.isoformat() if call.started_at else None,
                "duration_seconds": call.duration_seconds,
                "intent": call.intent,
                "outcome": call.outcome,
                "transcript": call.transcript
            }
            for call in calls
        ]
    }

@router.get("/{business_id}/bookings")
async def get_business_bookings(
    business_id: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """Get recent bookings for a business"""
    db_service = DBService(db)
    bookings = await db_service.get_business_bookings(business_id, limit)
    
    return {
        "business_id": business_id,
        "total": len(bookings),
        "bookings": [
            {
                "id": str(booking.id),
                "customer_name": booking.customer_name,
                "customer_phone": booking.customer_phone,
                "service": booking.service,
                "booking_datetime": booking.booking_datetime.isoformat(),
                "status": booking.status,
                "created_at": booking.created_at.isoformat()
            }
            for booking in bookings
        ]
    }


