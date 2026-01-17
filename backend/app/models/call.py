from sqlalchemy import Column, String, Integer, Float, DateTime, Text, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.core.database import Base

class Call(Base):
    __tablename__ = "calls"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"))
    
    # Twilio metadata
    call_sid = Column(String, unique=True, nullable=False)
    caller_phone = Column(String, nullable=False)
    
    # Call details
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    
    # Conversation
    transcript = Column(Text)
    intent = Column(String)  # booking, inquiry, complaint, etc.
    outcome = Column(String)  # booked, inquiry_handled, transferred, failed
    
    # AI Analysis
    sentiment_score = Column(Float)  # -1.0 to 1.0
    confidence_score = Column(Float)  # 0.0 to 1.0
    
    # Recording
    recording_url = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    business = relationship("Business", backref="calls")
    
    def __repr__(self):
        return f"<Call(id={self.id}, caller={self.caller_phone})>"