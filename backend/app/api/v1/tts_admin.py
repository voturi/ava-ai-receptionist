from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.db_service import DBService
from app.integrations.tts.greeting import generate_greeting_audio, generate_filler_audio, generate_all_fillers, FILLER_TEXTS
from app.integrations.tts.registry import get_voice_config

router = APIRouter()


class VoiceConfigPayload(BaseModel):
    """Payload for updating per-business TTS voice configuration."""

    provider: str
    model: str
    voice_id: str
    language: str = "en-AU"
    speed: float = 1.0
    pitch: float = 0.0
    style: str | None = None


class PolicyPayload(BaseModel):
    """Payload for creating or updating a policy."""

    topic: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1)


class FAQPayload(BaseModel):
    """Payload for creating or updating a FAQ."""

    topic: str = Field(..., min_length=1, max_length=100)
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)


@router.post("/greeting/{business_id}")
async def generate_greeting(business_id: str, db: AsyncSession = Depends(get_db)):
    """Generate and store a cached greeting audio URL for a business."""
    db_service = DBService(db)
    business = await db_service.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    ai_config = business.ai_config or {}
    # Use greeting from config, or generate one with business name
    greeting_text = ai_config.get("greeting")
    if not greeting_text or greeting_text == "Thanks for calling Marks Plumbing Servoces, I am Echo! How can I help you today?":
        # Generate personalized greeting with business name
        greeting_text = f"G'day! Welcome to {business.name}. How can I help you today?"
    voice_config = get_voice_config(ai_config)

    result = await generate_greeting_audio(business_id, greeting_text, voice_config)
    if not result.audio_url:
        raise HTTPException(
            status_code=500,
            detail=result.error or "Failed to generate greeting audio",
        )

    ai_config.setdefault("voice", {})
    ai_config["voice"]["greeting_audio_url"] = result.audio_url
    ai_config["greeting"] = greeting_text  # Store the actual greeting text used
    await db_service.update_business(business_id, {"ai_config": ai_config})

    return {"status": "ok", "audio_url": result.audio_url, "greeting_text": greeting_text}


@router.post("/thinking/{business_id}")
async def generate_thinking_clip(business_id: str, db: AsyncSession = Depends(get_db)):
    """Generate and store a cached thinking clip for a business."""
    db_service = DBService(db)
    business = await db_service.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    ai_config = business.ai_config or {}
    voice_config = get_voice_config(ai_config)
    thinking_text = "Just a moment while I check that for you."

    result = await generate_greeting_audio(business_id, thinking_text, voice_config)
    if not result.audio_url:
        raise HTTPException(
            status_code=500,
            detail=result.error or "Failed to generate thinking clip",
        )

    ai_config.setdefault("voice", {})
    ai_config["voice"]["thinking_audio_url"] = result.audio_url
    await db_service.update_business(business_id, {"ai_config": ai_config})

    return {"status": "ok", "audio_url": result.audio_url}


@router.post("/filler/{business_id}")
async def generate_filler_clips(business_id: str, db: AsyncSession = Depends(get_db)):
    """Generate and store all context-aware filler audio clips for a business.

    Generates multiple fillers:
    - checking: "Let me check that for you." (for questions)
    - noting: "Got it, just noting that down." (when user provides info)
    - processing: "Give me a moment to process that." (general)
    - thinking: "Let me think about that." (for complex questions)
    """
    db_service = DBService(db)
    business = await db_service.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    ai_config = business.ai_config or {}
    voice_config = get_voice_config(ai_config)

    # Generate all filler types
    results = await generate_all_fillers(business_id, voice_config)

    ai_config.setdefault("voice", {})
    ai_config.setdefault("fillers", {})

    urls = {}
    for filler_type, result in results.items():
        if result.audio_url:
            ai_config["fillers"][filler_type] = result.audio_url
            urls[filler_type] = result.audio_url

    # Keep backwards compat - set default filler_audio_url to "checking"
    if "checking" in urls:
        ai_config["voice"]["filler_audio_url"] = urls["checking"]

    await db_service.update_business(business_id, {"ai_config": ai_config})

    return {
        "status": "ok",
        "fillers": urls,
        "filler_texts": FILLER_TEXTS,
    }


@router.put("/voice/{business_id}")
async def update_voice_config(
    business_id: str,
    payload: VoiceConfigPayload,
    db: AsyncSession = Depends(get_db),
):
    """Update the voice configuration for a business."""
    db_service = DBService(db)
    business = await db_service.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    ai_config = business.ai_config or {}
    ai_config.setdefault("voice", {})
    ai_config["voice"].update(payload.model_dump())
    await db_service.update_business(business_id, {"ai_config": ai_config})

    return {"status": "ok", "voice": ai_config["voice"]}


@router.post("/policies/{business_id}")
async def create_policy(
    business_id: str,
    payload: PolicyPayload,
    db: AsyncSession = Depends(get_db),
):
    """Create a policy for a business."""
    db_service = DBService(db)
    business = await db_service.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    policy = await db_service.create_policy({
        "business_id": business_id,
        "topic": payload.topic,
        "content": payload.content,
    })

    return {
        "status": "ok",
        "policy": {
            "id": str(policy.id),
            "business_id": str(policy.business_id),
            "topic": policy.topic,
            "content": policy.content,
            "updated_at": policy.updated_at,
        },
    }


@router.put("/policies/{business_id}/{policy_id}")
async def update_policy(
    business_id: str,
    policy_id: str,
    payload: PolicyPayload,
    db: AsyncSession = Depends(get_db),
):
    """Update a policy by ID."""
    db_service = DBService(db)
    business = await db_service.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    policy = await db_service.update_policy(policy_id, {
        "topic": payload.topic,
        "content": payload.content,
    })
    if not policy or str(policy.business_id) != str(business.id):
        raise HTTPException(status_code=404, detail="Policy not found")

    return {
        "status": "ok",
        "policy": {
            "id": str(policy.id),
            "business_id": str(policy.business_id),
            "topic": policy.topic,
            "content": policy.content,
            "updated_at": policy.updated_at,
        },
    }


@router.get("/policies/{business_id}")
async def list_policies(
    business_id: str,
    topic: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List policies for a business, optionally filtered by topic."""
    db_service = DBService(db)
    business = await db_service.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    policies = await db_service.get_policies(business_id, topic=topic)
    return {
        "status": "ok",
        "policies": [
            {
                "id": str(policy.id),
                "business_id": str(policy.business_id),
                "topic": policy.topic,
                "content": policy.content,
                "updated_at": policy.updated_at,
            }
            for policy in policies
        ],
    }


@router.post("/faqs/{business_id}")
async def create_faq(
    business_id: str,
    payload: FAQPayload,
    db: AsyncSession = Depends(get_db),
):
    """Create an FAQ for a business."""
    db_service = DBService(db)
    business = await db_service.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    faq = await db_service.create_faq({
        "business_id": business_id,
        "topic": payload.topic,
        "question": payload.question,
        "answer": payload.answer,
        "tags": payload.tags,
    })

    return {
        "status": "ok",
        "faq": {
            "id": str(faq.id),
            "business_id": str(faq.business_id),
            "topic": faq.topic,
            "question": faq.question,
            "answer": faq.answer,
            "tags": faq.tags,
            "updated_at": faq.updated_at,
        },
    }


@router.put("/faqs/{business_id}/{faq_id}")
async def update_faq(
    business_id: str,
    faq_id: str,
    payload: FAQPayload,
    db: AsyncSession = Depends(get_db),
):
    """Update an FAQ by ID."""
    db_service = DBService(db)
    business = await db_service.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    faq = await db_service.update_faq(faq_id, {
        "topic": payload.topic,
        "question": payload.question,
        "answer": payload.answer,
        "tags": payload.tags,
    })
    if not faq or str(faq.business_id) != str(business.id):
        raise HTTPException(status_code=404, detail="FAQ not found")

    return {
        "status": "ok",
        "faq": {
            "id": str(faq.id),
            "business_id": str(faq.business_id),
            "topic": faq.topic,
            "question": faq.question,
            "answer": faq.answer,
            "tags": faq.tags,
            "updated_at": faq.updated_at,
        },
    }


@router.get("/faqs/{business_id}")
async def list_faqs(
    business_id: str,
    topic: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List FAQs for a business, optionally filtered by topic."""
    db_service = DBService(db)
    business = await db_service.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    faqs = await db_service.get_faqs(business_id, topic=topic)
    return {
        "status": "ok",
        "faqs": [
            {
                "id": str(faq.id),
                "business_id": str(faq.business_id),
                "topic": faq.topic,
                "question": faq.question,
                "answer": faq.answer,
                "tags": faq.tags,
                "updated_at": faq.updated_at,
            }
            for faq in faqs
        ],
    }
