from sqlalchemy import select
from sqlalchemy import or_
import re
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Business, Call, Booking, Policy, FAQ
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

    async def get_latest_booking_by_phone(
        self,
        business_id: str,
        customer_phone: str,
    ) -> Optional[Booking]:
        """Get the most recent booking by customer phone within a business."""
        try:
            b_uuid = uuid.UUID(business_id)
        except ValueError:
            return None

        result = await self.session.execute(
            select(Booking)
            .where(
                Booking.business_id == b_uuid,
                Booking.customer_phone == customer_phone,
            )
            .order_by(Booking.booking_datetime.desc())
            .limit(1)
        )
        return result.scalars().first()

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

    # ==================== POLICIES ====================

    async def create_policy(self, data: dict) -> Policy:
        """Create a new policy."""
        policy = Policy(**data)
        self.session.add(policy)
        await self.session.commit()
        await self.session.refresh(policy)
        return policy

    async def get_policies(
        self,
        business_id: str,
        topic: Optional[str] = None,
        limit: int = 20,
    ) -> List[Policy]:
        """Get policies for a business, optionally filtered by topic."""
        try:
            b_uuid = uuid.UUID(business_id)
        except ValueError:
            return []

        query = select(Policy).where(Policy.business_id == b_uuid)
        if topic:
            normalized = self._normalize_topic(topic)
            aliases = self._topic_aliases(normalized)
            print(f"🧭 Policy topic: raw='{topic}' normalized='{normalized}' aliases={aliases}")
            query = query.where(
                or_(
                    Policy.topic == normalized,
                    Policy.topic.in_(aliases),
                    Policy.topic.ilike(f"%{normalized}%"),
                )
            )
        query = query.order_by(Policy.updated_at.desc()).limit(limit)

        result = await self.session.execute(query)
        return result.scalars().all()

    async def update_policy(self, policy_id: str, data: dict) -> Optional[Policy]:
        """Update a policy by ID."""
        try:
            p_uuid = uuid.UUID(policy_id)
        except ValueError:
            return None

        result = await self.session.execute(
            select(Policy).where(Policy.id == p_uuid)
        )
        policy = result.scalar_one_or_none()
        if policy:
            for key, value in data.items():
                setattr(policy, key, value)
            await self.session.commit()
            await self.session.refresh(policy)
        return policy

    # ==================== FAQS ====================

    async def create_faq(self, data: dict) -> FAQ:
        """Create a new FAQ."""
        faq = FAQ(**data)
        self.session.add(faq)
        await self.session.commit()
        await self.session.refresh(faq)
        return faq

    async def get_faqs(
        self,
        business_id: str,
        topic: Optional[str] = None,
        limit: int = 50,
    ) -> List[FAQ]:
        """Get FAQs for a business, optionally filtered by topic."""
        try:
            b_uuid = uuid.UUID(business_id)
        except ValueError:
            return []

        query = select(FAQ).where(FAQ.business_id == b_uuid)
        if topic:
            normalized = self._normalize_topic(topic)
            aliases = self._topic_aliases(normalized)
            print(f"🧭 FAQ topic: raw='{topic}' normalized='{normalized}' aliases={aliases}")
            query = query.where(
                or_(
                    FAQ.topic == normalized,
                    FAQ.topic.in_(aliases),
                    FAQ.topic.ilike(f"%{normalized}%"),
                )
            )
        query = query.order_by(FAQ.updated_at.desc()).limit(limit)

        result = await self.session.execute(query)
        return result.scalars().all()

    def _normalize_topic(self, topic: str) -> str:
        value = topic.strip().lower()
        value = value.replace("call out", "callout").replace("call-out", "callout")
        value = re.sub(r"[^\w\\s-]", "", value)
        value = re.sub(r"[\\s-]+", "_", value)
        value = value.strip("_")
        return value

    def _topic_aliases(self, normalized: str) -> list[str]:
        aliases = {
            "call_out_fee": "callout_fee",
            "callout_fee": "call_out_fee",
            "after_hours": "afterhours",
            "late": "late_arrival",
            "late_arrival": "late",
            "emergency": "emergency_plumbing",
            "emergency_plumbing": "emergency",
            "no_power": "power_outage",
            "power_outage": "no_power",
            "refund_policies": "refunds",
            "refunds": "refund_policy",
            "refund_policy": "refunds",
        }
        alias = aliases.get(normalized)
        return [alias] if alias else []

    async def update_faq(self, faq_id: str, data: dict) -> Optional[FAQ]:
        """Update an FAQ by ID."""
        try:
            f_uuid = uuid.UUID(faq_id)
        except ValueError:
            return None

        result = await self.session.execute(
            select(FAQ).where(FAQ.id == f_uuid)
        )
        faq = result.scalar_one_or_none()
        if faq:
            for key, value in data.items():
                setattr(faq, key, value)
            await self.session.commit()
            await self.session.refresh(faq)
        return faq
