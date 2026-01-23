from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Business, Policy, FAQ

router = APIRouter()


class PolicyItem(BaseModel):
    topic: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1)


class FAQItem(BaseModel):
    topic: str = Field(..., min_length=1, max_length=100)
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)


class TradiesOnboardingPayload(BaseModel):
    business_name: str = Field(..., min_length=1)
    business_type: str = Field(..., min_length=1)
    tone: str | None = None
    language: str | None = None
    phone: str | None = None
    email: str | None = None
    twilio_number: str | None = None
    services: list[str] = Field(default_factory=list)
    working_hours: dict = Field(default_factory=dict)
    policies: list[PolicyItem] = Field(default_factory=list)
    faqs: list[FAQItem] = Field(default_factory=list)
    emergency_guidance: str | None = None
    booking_preferences: dict | None = None


async def _get_business(session: AsyncSession, business_id: str) -> Optional[Business]:
    result = await session.execute(
        select(Business).where(Business.id == business_id)
    )
    return result.scalar_one_or_none()


def _merge_ai_config(existing: dict, payload: TradiesOnboardingPayload) -> dict:
    ai_config = dict(existing or {})
    if payload.tone:
        ai_config["tone"] = payload.tone
    if payload.language:
        ai_config["language"] = payload.language
    ai_config.setdefault("agent_name", "Echo")
    onboarding = ai_config.get("onboarding", {})
    if payload.emergency_guidance:
        onboarding["emergency_guidance"] = payload.emergency_guidance
    if payload.booking_preferences is not None:
        onboarding["booking_preferences"] = payload.booking_preferences
    if onboarding:
        ai_config["onboarding"] = onboarding
    return ai_config


@router.post("/tradies")
async def create_tradies_onboarding(
    payload: TradiesOnboardingPayload,
    db: AsyncSession = Depends(get_db),
):
    """Create a new tradies tenant and persist onboarding data."""
    business = Business(
        name=payload.business_name,
        industry=payload.business_type,
        phone=payload.phone,
        email=payload.email,
        twilio_number=payload.twilio_number,
        services=payload.services,
        working_hours=payload.working_hours,
        ai_config=_merge_ai_config({}, payload),
    )
    db.add(business)
    await db.commit()
    await db.refresh(business)

    if payload.policies:
        db.add_all([
            Policy(
                business_id=business.id,
                topic=policy.topic,
                content=policy.content,
            )
            for policy in payload.policies
        ])
    if payload.faqs:
        db.add_all([
            FAQ(
                business_id=business.id,
                topic=faq.topic,
                question=faq.question,
                answer=faq.answer,
                tags=faq.tags,
            )
            for faq in payload.faqs
        ])

    await db.commit()

    return {
        "status": "ok",
        "business_id": str(business.id),
        "policies_created": len(payload.policies),
        "faqs_created": len(payload.faqs),
    }


@router.put("/tradies/{business_id}")
async def update_tradies_onboarding(
    business_id: str,
    payload: TradiesOnboardingPayload,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing tradies tenant and replace onboarding data."""
    business = await _get_business(db, business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    business.name = payload.business_name
    business.industry = payload.business_type
    business.phone = payload.phone
    business.email = payload.email
    business.twilio_number = payload.twilio_number
    business.services = payload.services
    business.working_hours = payload.working_hours
    business.ai_config = _merge_ai_config(business.ai_config or {}, payload)

    await db.execute(delete(Policy).where(Policy.business_id == business.id))
    await db.execute(delete(FAQ).where(FAQ.business_id == business.id))

    if payload.policies:
        db.add_all([
            Policy(
                business_id=business.id,
                topic=policy.topic,
                content=policy.content,
            )
            for policy in payload.policies
        ])
    if payload.faqs:
        db.add_all([
            FAQ(
                business_id=business.id,
                topic=faq.topic,
                question=faq.question,
                answer=faq.answer,
                tags=faq.tags,
            )
            for faq in payload.faqs
        ])

    await db.commit()

    return {
        "status": "ok",
        "business_id": str(business.id),
        "policies_created": len(payload.policies),
        "faqs_created": len(payload.faqs),
    }


@router.delete("/tradies/{business_id}")
async def delete_tradies_onboarding(
    business_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete tradies onboarding data (policies, FAQs, services, hours)."""
    business = await _get_business(db, business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    await db.execute(delete(Policy).where(Policy.business_id == business.id))
    await db.execute(delete(FAQ).where(FAQ.business_id == business.id))

    business.services = []
    business.working_hours = {}
    ai_config = business.ai_config or {}
    ai_config.pop("onboarding", None)
    business.ai_config = ai_config

    await db.commit()

    return {"status": "ok", "business_id": str(business.id)}
