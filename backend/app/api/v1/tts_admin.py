from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.db_service import DBService
from app.integrations.tts.greeting import generate_greeting_audio
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


@router.post("/greeting/{business_id}")
async def generate_greeting(business_id: str, db: AsyncSession = Depends(get_db)):
    """Generate and store a cached greeting audio URL for a business."""
    db_service = DBService(db)
    business = await db_service.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    ai_config = business.ai_config or {}
    greeting_text = ai_config.get("greeting", "Hello! How can I help you today?")
    voice_config = get_voice_config(ai_config)

    result = await generate_greeting_audio(business_id, greeting_text, voice_config)
    if not result.audio_url:
        raise HTTPException(
            status_code=500,
            detail=result.error or "Failed to generate greeting audio",
        )

    ai_config.setdefault("voice", {})
    ai_config["voice"]["greeting_audio_url"] = result.audio_url
    await db_service.update_business(business_id, {"ai_config": ai_config})

    return {"status": "ok", "audio_url": result.audio_url}


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
