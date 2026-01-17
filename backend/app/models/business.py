from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from app.core.database import Base

class Business(Base):
    __tablename__ = "businesses"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    industry = Column(String, default="salon")
    phone = Column(String)
    email = Column(String)
    
    # Twilio
    twilio_number = Column(String, unique=True)
    
    # AI Configuration (stored as JSON)
    ai_config = Column(JSON, default={
        "greeting": "Thanks for calling! How can I help you today?",
        "voice_id": "Polly.Nicole",
        "language": "en-AU"
    })
    
    # Business Configuration
    services = Column(JSON, default=[])  # List of services offered
    working_hours = Column(JSON, default={})  # Business hours
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Business(id={self.id}, name={self.name})>"