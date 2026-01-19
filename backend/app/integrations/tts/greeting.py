from __future__ import annotations

from app.integrations.tts.base import AudioResult, VoiceConfig
from app.integrations.tts.registry import resolve_provider


async def generate_greeting_audio(
    business_id: str,
    greeting_text: str,
    voice: VoiceConfig,
) -> AudioResult:
    """Generate and store a greeting audio clip, returning the synthesis result."""
    provider = resolve_provider(voice)
    return await provider.synthesize(greeting_text, voice)
