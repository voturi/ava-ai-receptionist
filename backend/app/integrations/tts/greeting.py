from __future__ import annotations

from app.integrations.tts.base import AudioResult, VoiceConfig
from app.integrations.tts.registry import resolve_provider

# Context-aware filler texts
FILLER_TEXTS = {
    "checking": "Let me check that for you.",
    "noting": "Got it, just noting that down.",
    "processing": "Give me a moment to process that.",
    "thinking": "Let me think about that.",
}

# Keywords that indicate the customer is providing information (not asking)
INFO_KEYWORDS = [
    "my name is", "i'm", "i am", "my number is", "my phone", "phone number",
    "my email", "email is", "it's", "that's", "yes", "yeah", "yep", "correct",
    "right", "sure", "okay", "ok",
]


def select_filler_type(user_speech: str | None) -> str:
    """Select appropriate filler type based on user's speech content."""
    if not user_speech:
        return "checking"

    speech_lower = user_speech.lower()

    # If user is providing information, use "noting" filler
    for keyword in INFO_KEYWORDS:
        if keyword in speech_lower:
            return "noting"

    # Default to "checking" for questions/requests
    return "checking"


async def generate_greeting_audio(
    business_id: str,
    greeting_text: str,
    voice: VoiceConfig,
) -> AudioResult:
    """Generate and store a greeting audio clip, returning the synthesis result."""
    provider = resolve_provider(voice)
    return await provider.synthesize(greeting_text, voice)


async def generate_filler_audio(
    business_id: str,
    voice: VoiceConfig,
    filler_type: str = "checking",
) -> AudioResult:
    """Generate and store a filler audio clip for proactive playback during TTS synthesis."""
    provider = resolve_provider(voice)
    text = FILLER_TEXTS.get(filler_type, FILLER_TEXTS["checking"])
    return await provider.synthesize(text, voice)


async def generate_all_fillers(
    business_id: str,
    voice: VoiceConfig,
) -> dict[str, AudioResult]:
    """Generate all filler audio clips for a business."""
    provider = resolve_provider(voice)
    results = {}
    for filler_type, text in FILLER_TEXTS.items():
        results[filler_type] = await provider.synthesize(text, voice)
    return results
