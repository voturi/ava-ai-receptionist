from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Business, Call, Booking
from typing import Optional, List
from datetime import datetime
import uuid
from sqlalchemy.orm.attributes import flag_modified

class DBService:
    """
    Service for database operations
    """
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    # ==================== BUSINESSES ====================
    
    async def get_business(self, business_id: str) -> Optional[Business]:
        """Get business by ID"""
        try:
            b_uuid = uuid.UUID(business_id)
        except ValueError:
            return None
            
        result = await self.session.execute(
            select(Business).where(Business.id == b_uuid)
        )
        return result.scalar_one_or_none()
    
    async def get_business_by_phone(self, phone: str) -> Optional[Business]:
        """Get business by Twilio phone number"""
        result = await self.session.execute(
            select(Business).where(Business.twilio_number == phone)
        )
        return result.scalar_one_or_none()
    
    async def create_business(self, data: dict) -> Business:
        """Create new business"""
        business = Business(**data)
        self.session.add(business)
        await self.session.commit()
        await self.session.refresh(business)
        return business

    async def update_business(self, business_id: str, data: dict) -> Optional[Business]:
        """Update business fields by ID."""
        business = await self.get_business(business_id)
        if business:
            for key, value in data.items():
                setattr(business, key, value)
                if key == "ai_config":
                    flag_modified(business, "ai_config")
            await self.session.commit()
            await self.session.refresh(business)
        return business
    
    # ==================== CALLS ====================
    
    async def create_call(self, data: dict) -> Call:
        """Create new call record"""
        call = Call(**data)
        self.session.add(call)
        await self.session.commit()
        await self.session.refresh(call)
        return call
    
    async def get_call(self, call_id: str) -> Optional[Call]:
        """Get call by ID"""
        try:
            c_uuid = uuid.UUID(call_id)
        except ValueError:
            return None
            
        result = await self.session.execute(
            select(Call).where(Call.id == c_uuid)
        )
        return result.scalar_one_or_none()
    
    async def get_call_by_sid(self, call_sid: str) -> Optional[Call]:
        """Get call by Twilio Call SID"""
        result = await self.session.execute(
            select(Call).where(Call.call_sid == call_sid)
        )
        return result.scalar_one_or_none()
    
    async def update_call(self, call_id: str, data: dict) -> Optional[Call]:
        """Update call record"""
        call = await self.get_call(call_id)
        if call:
            for key, value in data.items():
                setattr(call, key, value)
            await self.session.commit()
            await self.session.refresh(call)
        return call
    
    async def get_business_calls(
        self, 
        business_id: str, 
        limit: int = 50
    ) -> List[Call]:
        """Get recent calls for business"""
        try:
            b_uuid = uuid.UUID(business_id)
        except ValueError:
            return []
            
        result = await self.session.execute(
            select(Call)
            .where(Call.business_id == b_uuid)
            .order_by(Call.started_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
    
    # ==================== BOOKINGS ====================
    
    async def create_booking(self, data: dict) -> Booking:
        """Create new booking"""
        booking = Booking(**data)
        self.session.add(booking)
        await self.session.commit()
        await self.session.refresh(booking)
        return booking
    
    async def get_booking(self, booking_id: str) -> Optional[Booking]:
        """Get booking by ID"""
        try:
            b_uuid = uuid.UUID(booking_id)
        except ValueError:
            return None
            
        result = await self.session.execute(
            select(Booking).where(Booking.id == b_uuid)
        )
        return result.scalar_one_or_none()
    
    async def get_business_bookings(
        self, 
        business_id: str, 
        limit: int = 50
    ) -> List[Booking]:
        """Get recent bookings for business"""
        try:
            b_uuid = uuid.UUID(business_id)
        except ValueError:
            return []
            
        result = await self.session.execute(
            select(Booking)
            .where(Booking.business_id == b_uuid)
            .order_by(Booking.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()
    
    async def update_booking(
        self, 
        booking_id: str, 
        data: dict
    ) -> Optional[Booking]:
        """Update booking"""
        booking = await self.get_booking(booking_id)
        if booking:
            for key, value in data.items():
                setattr(booking, key, value)
            await self.session.commit()
            await self.session.refresh(booking)
        return booking
