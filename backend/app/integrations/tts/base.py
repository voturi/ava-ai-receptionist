from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class VoiceConfig:
    provider: str
    voice_id: str
    model: str = "aura-2"
    language: str = "en-AU"
    speed: float = 1.0
    pitch: float = 0.0
    style: Optional[str] = None


@dataclass
class AudioResult:
    audio_url: Optional[str]
    content_type: Optional[str]
    duration_ms: Optional[int]
    cached: bool
    error: Optional[str] = None


class TTSProvider(Protocol):
    name: str

    async def synthesize(self, text: str, voice: VoiceConfig) -> AudioResult:
        """Synthesize text into audio and return a URL-backed result."""
        ...
