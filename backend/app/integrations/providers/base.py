from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Protocol


@dataclass
class CustomerInfo:
    name: str
    phone: str
    email: Optional[str] = None


@dataclass
class BookingContext:
    business_id: str
    business_name: str
    service: str
    requested_datetime: Optional[datetime]
    customer: CustomerInfo
    metadata: dict[str, Any]


@dataclass
class AvailabilityResult:
    available: bool
    reason: Optional[str] = None


@dataclass
class BookingIntent:
    status: str  # confirmed | pending | declined
    message_override: Optional[str] = None
    external_reference: Optional[str] = None


class BookingProvider(Protocol):
    name: str

    async def check_availability(self, context: BookingContext) -> AvailabilityResult:
        ...

    async def create_booking(self, context: BookingContext) -> BookingIntent:
        ...

    async def after_booking(self, context: BookingContext, booking_id: str) -> None:
        ...
