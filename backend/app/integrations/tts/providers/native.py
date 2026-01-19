from __future__ import annotations

from app.integrations.tts.base import AudioResult, VoiceConfig


class NativeTTSProvider:
    name = "native"

    async def synthesize(self, text: str, voice: VoiceConfig) -> AudioResult:
        return AudioResult(
            audio_url=None,
            content_type=None,
            duration_ms=None,
            cached=False,
            error="native_provider_no_audio",
        )
