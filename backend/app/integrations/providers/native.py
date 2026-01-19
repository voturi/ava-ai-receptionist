from __future__ import annotations

from app.integrations.providers.base import AvailabilityResult, BookingContext, BookingIntent


class NativeBookingProvider:
    name = "native"

    async def check_availability(self, context: BookingContext) -> AvailabilityResult:
        return AvailabilityResult(available=True)

    async def create_booking(self, context: BookingContext) -> BookingIntent:
        return BookingIntent(status="confirmed")

    async def after_booking(self, context: BookingContext, booking_id: str) -> None:
        return None
