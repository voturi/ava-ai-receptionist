from __future__ import annotations

from typing import Any

from app.integrations.tts.base import VoiceConfig
from app.integrations.tts.providers.native import NativeTTSProvider
from app.integrations.tts.providers.deepgram import DeepgramTTSProvider

# Lazy-loaded provider instances (avoids Supabase client creation at import time)
_provider_instances: dict[str, Any] = {}


def _get_provider_instance(name: str):
    """Get or create a provider instance lazily."""
    if name not in _provider_instances:
        if name == "native":
            _provider_instances[name] = NativeTTSProvider()
        elif name == "deepgram":
            _provider_instances[name] = DeepgramTTSProvider()
        else:
            _provider_instances[name] = NativeTTSProvider()
    return _provider_instances[name]


def get_voice_config(ai_config: dict[str, Any] | None) -> VoiceConfig:
    """Build a voice configuration object from business AI config."""
    ai_config = ai_config or {}
    voice = ai_config.get("voice", {})
    return VoiceConfig(
        provider=voice.get("provider", "native"),
        model=voice.get("model", "aura-2"),
        voice_id=voice.get("voice_id", "default"),
        language=voice.get("language", "en-AU"),
        speed=voice.get("speed", 1.0),
        pitch=voice.get("pitch", 0.0),
        style=voice.get("style"),
    )


def resolve_provider(voice: VoiceConfig):
    """Resolve a provider instance by voice configuration."""
    return _get_provider_instance(voice.provider)
