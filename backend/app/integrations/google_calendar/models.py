"""Calendar event data models"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class CalendarEvent:
    """Represents a booking event for Google Calendar"""
    
    title: str                      # "Haircut - Jane Smith"
    description: str                # Booking details, phone, etc
    start_time: datetime            # Booking datetime
    end_time: datetime              # Start + service duration
    customer_phone: str             # Stored in description
    service: str                    # What was booked
    business_id: str                # Which business
    booking_id: str                 # Link back to our DB
    customer_email: Optional[str] = None  # To send invitations
    
    def to_google_event(self) -> dict:
        """Convert to Google Calendar API event format"""
        return {
            "summary": self.title,
            "description": f"{self.description}\nPhone: {self.customer_phone}",
            "start": {
                "dateTime": self.start_time.isoformat(),
                "timeZone": "Australia/Sydney",
            },
            "end": {
                "dateTime": self.end_time.isoformat(),
                "timeZone": "Australia/Sydney",
            },
            "attendees": [
                {"email": self.customer_email}
            ] if self.customer_email else [],
        }
