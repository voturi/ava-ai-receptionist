from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.core.database import AsyncSessionLocal
from app.services.db_service import DBService


def _dt_to_iso(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    return value.isoformat()


class ToolRouter:
    """Executes tool calls against the database (tenant-scoped, read-only)."""

    async def execute(
        self,
        tool_name: str,
        arguments: dict,
        *,
        business_id: str,
        caller_phone: Optional[str] = None,
    ) -> dict[str, Any]:
        if not business_id:
            return {"error": "missing_business_id"}

        if tool_name == "get_latest_booking":
            customer_phone = arguments.get("customer_phone") or caller_phone
            if not customer_phone:
                return {"error": "missing_customer_phone"}
            return await self._get_latest_booking(business_id, customer_phone)

        if tool_name == "get_booking_by_id":
            booking_id = arguments.get("booking_id")
            if not booking_id:
                return {"error": "missing_booking_id"}
            return await self._get_booking_by_id(business_id, booking_id)

        if tool_name == "get_business_services":
            return await self._get_business_services(business_id)

        if tool_name == "get_working_hours":
            return await self._get_working_hours(business_id)

        if tool_name == "get_policies":
            topic = arguments.get("topic")
            if not topic:
                return {"error": "missing_topic"}
            return await self._get_policies(business_id, topic)

        if tool_name == "get_faqs":
            topic = arguments.get("topic")
            if not topic:
                return {"error": "missing_topic"}
            return await self._get_faqs(business_id, topic)

        return {"error": "unknown_tool"}

    async def _get_latest_booking(self, business_id: str, customer_phone: str) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            db_service = DBService(session)
            booking = await db_service.get_latest_booking_by_phone(business_id, customer_phone)
            if not booking:
                return {"booking": None}
            return {
                "booking": {
                    "booking_id": str(booking.id),
                    "status": booking.status,
                    "service": booking.service,
                    "booking_datetime": _dt_to_iso(booking.booking_datetime),
                    "customer_name": booking.customer_name,
                }
            }

    async def _get_booking_by_id(self, business_id: str, booking_id: str) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            db_service = DBService(session)
            booking = await db_service.get_booking(booking_id)
            if not booking or str(booking.business_id) != str(business_id):
                return {"booking": None}
            return {
                "booking": {
                    "booking_id": str(booking.id),
                    "status": booking.status,
                    "service": booking.service,
                    "booking_datetime": _dt_to_iso(booking.booking_datetime),
                    "duration_minutes": booking.duration_minutes,
                    "customer_name": booking.customer_name,
                    "customer_phone": booking.customer_phone,
                }
            }

    async def _get_business_services(self, business_id: str) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            db_service = DBService(session)
            business = await db_service.get_business(business_id)
            services = business.services if business else []
            return {"services": services or []}

    async def _get_working_hours(self, business_id: str) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            db_service = DBService(session)
            business = await db_service.get_business(business_id)
            working_hours = business.working_hours if business else {}
            return {"working_hours": working_hours or {}}

    async def _get_policies(self, business_id: str, topic: str) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            db_service = DBService(session)
            policies = await db_service.get_policies(business_id, topic=topic)
            return {
                "topic": topic,
                "policies": [
                    {
                        "id": str(policy.id),
                        "topic": policy.topic,
                        "content": policy.content,
                        "updated_at": _dt_to_iso(policy.updated_at),
                    }
                    for policy in policies
                ],
            }

    async def _get_faqs(self, business_id: str, topic: str) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            db_service = DBService(session)
            faqs = await db_service.get_faqs(business_id, topic=topic)
            return {
                "topic": topic,
                "faqs": [
                    {
                        "id": str(faq.id),
                        "topic": faq.topic,
                        "question": faq.question,
                        "answer": faq.answer,
                        "tags": faq.tags or [],
                        "updated_at": _dt_to_iso(faq.updated_at),
                    }
                    for faq in faqs
                ],
            }
