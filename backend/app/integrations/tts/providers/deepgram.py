from __future__ import annotations

import os
import time
from typing import Optional

import httpx

from app.integrations.tts.base import AudioResult, VoiceConfig
from app.integrations.tts.metrics import TTSMetrics, now_iso
from app.integrations.tts.storage import AudioStorage, get_storage_config


class DeepgramTTSProvider:
    """Deepgram TTS provider that uploads audio to Supabase Storage."""

    name = "deepgram"

    def __init__(self, storage: Optional[AudioStorage] = None):
        """Initialize provider with optional storage client."""
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        if not self.api_key:
            raise RuntimeError("Missing DEEPGRAM_API_KEY")
        self.storage = storage or AudioStorage(get_storage_config())

    async def synthesize(self, text: str, voice: VoiceConfig) -> AudioResult:
        """Synthesize text to speech and return a signed audio URL."""
        voice_key = f"{voice.provider}:{voice.model}:{voice.voice_id}:{voice.language}:{voice.speed}:{voice.pitch}:{voice.style}"
        content_hash = self.storage.compute_hash(text, voice_key)
        audio_path = self.storage.build_audio_path("global", self.name, content_hash)

        start = time.time()
        signed_url_start = time.time()
        signed_url = self.storage.create_signed_url(audio_path)
        signed_url_ms = int((time.time() - signed_url_start) * 1000)
        if signed_url:
            metrics = TTSMetrics(
                event="tts.synthesize",
                business_id=None,
                provider=self.name,
                voice_id=voice.voice_id,
                text_hash=content_hash,
                cached=True,
                latency_ms=int((time.time() - start) * 1000),
                storage_upload_ms=None,
                signed_url_ms=signed_url_ms,
                success=True,
                error=None,
                timestamp=now_iso(),
            )
            metrics.log()
            return AudioResult(
                audio_url=signed_url,
                content_type="audio/mpeg",
                duration_ms=None,
                cached=True,
            )

        payload = text
        params = {
            "model": voice.model,
            "encoding": "mp3",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://api.deepgram.com/v1/speak",
                params=params,
                headers={
                    "Authorization": f"Token {self.api_key}",
                    "Content-Type": "text/plain",
                },
                content=payload,
            )
        if response.status_code >= 400:
            error_detail = response.text.strip()
            metrics = TTSMetrics(
                event="tts.synthesize",
                business_id=None,
                provider=self.name,
                voice_id=voice.voice_id,
                text_hash=content_hash,
                cached=False,
                latency_ms=int((time.time() - start) * 1000),
                storage_upload_ms=None,
                signed_url_ms=None,
                success=False,
                error=f"deepgram_error:{response.status_code}:{error_detail}",
                timestamp=now_iso(),
            )
            metrics.log()
            return AudioResult(
                audio_url=None,
                content_type=None,
                duration_ms=None,
                cached=False,
                error=f"deepgram_error:{response.status_code}:{error_detail}",
            )

        audio_bytes = response.content
        upload_start = time.time()
        self.storage.upload_audio(audio_path, audio_bytes)
        upload_ms = int((time.time() - upload_start) * 1000)
        signed_url_start = time.time()
        signed_url = self.storage.create_signed_url(audio_path)
        signed_url_ms = int((time.time() - signed_url_start) * 1000)
        latency_ms = int((time.time() - start) * 1000)
        metrics = TTSMetrics(
            event="tts.synthesize",
            business_id=None,
            provider=self.name,
            voice_id=voice.voice_id,
            text_hash=content_hash,
            cached=False,
            latency_ms=latency_ms,
            storage_upload_ms=upload_ms,
            signed_url_ms=signed_url_ms,
            success=bool(signed_url),
            error=None if signed_url else "missing_signed_url",
            timestamp=now_iso(),
        )
        metrics.log()
        return AudioResult(
            audio_url=signed_url,
            content_type="audio/mpeg",
            duration_ms=latency_ms,
            cached=False,
        )
