from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from supabase import create_client, Client


@dataclass
class StorageConfig:
    """Configuration for Supabase Storage access."""

    url: str
    service_key: str
    bucket: str = "tts-audio"
    signed_url_ttl_seconds: int = 1800
    public_urls: bool = False


class AudioStorage:
    """Supabase Storage helper for uploading and signing TTS audio files."""

    def __init__(self, config: StorageConfig):
        """Initialize storage with Supabase credentials."""
        self.config = config
        self.client: Client = create_client(config.url, config.service_key)

    def build_audio_path(self, business_id: str, provider: str, content_hash: str) -> str:
        """Return a deterministic storage path for a given audio asset."""
        return f"tts/{business_id}/{provider}/{content_hash}.mp3"

    def compute_hash(self, text: str, voice_key: str) -> str:
        """Compute a stable hash for text+voice configuration."""
        normalized = " ".join(text.strip().split())
        digest = hashlib.sha256(f"{voice_key}|{normalized}".encode("utf-8")).hexdigest()
        return digest

    def upload_audio(self, path: str, audio_bytes: bytes, content_type: str = "audio/mpeg") -> None:
        """Upload audio bytes to Supabase Storage at the given path."""
        self.client.storage.from_(self.config.bucket).upload(
            path,
            audio_bytes,
            {
                "content-type": content_type,
                "cache-control": "public, max-age=31536000",
                "upsert": "true",
            },
        )

    def create_signed_url(self, path: str) -> Optional[str]:
        """Create a signed URL for the given object path."""
        if self.config.public_urls:
            return self.public_url(path) if self.exists(path) else None
        try:
            response = self.client.storage.from_(self.config.bucket).create_signed_url(
                path,
                self.config.signed_url_ttl_seconds,
            )
        except Exception:
            return None
        return response.get("signedURL")

    def exists(self, path: str) -> bool:
        """Return True if the object exists in the bucket."""
        try:
            return self.client.storage.from_(self.config.bucket).exists(path)
        except Exception:
            return False

    def public_url(self, path: str) -> str:
        """Return the public URL for an object path."""
        base = self.config.url.rstrip("/")
        return f"{base}/storage/v1/object/public/{self.config.bucket}/{path}"


def get_storage_config() -> StorageConfig:
    """Load Supabase Storage config from environment variables."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY for TTS storage")
    url = url.strip()
    if not url.endswith("/"):
        url = f"{url}/"
    public_urls = os.getenv("TTS_PUBLIC_URLS", "false").lower() in {"1", "true", "yes"}
    return StorageConfig(url=url, service_key=key, public_urls=public_urls)
