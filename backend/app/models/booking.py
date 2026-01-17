from sqlalchemy import Column, String,Integer, JSON, DateTime, Numeric, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.core.database import Base

class Booking(Base):
    __tablename__ = "bookings"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"))
    call_id = Column(UUID(as_uuid=True), ForeignKey("calls.id"), nullable=True)
    
    # Customer Info
    customer_name = Column(String, nullable=False)
    customer_phone = Column(String, nullable=False)
    customer_email = Column(String, nullable=True)
    
    # Booking Details
    service = Column(String, nullable=False)
    booking_datetime = Column(DateTime, nullable=False)
    duration_minutes = Column(Integer, default=60)
    
    # Status
    status = Column(String, default="pending")  # pending, confirmed, cancelled, completed
    confirmed_at = Column(DateTime, nullable=True)
    
    # Revenue
    price = Column(Numeric(10, 2), nullable=True)
    
    # Notes
    customer_notes = Column(Text, nullable=True)
    internal_notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    business = relationship("Business", backref="bookings")
    call = relationship("Call", backref="bookings")
    
    def __repr__(self):
        return f"<Booking(id={self.id}, customer={self.customer_name}, service={self.service})>"
