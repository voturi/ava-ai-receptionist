from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class TTSMetrics:
    """Lightweight metrics payload for TTS operations."""

    event: str
    business_id: Optional[str]
    provider: str
    voice_id: str
    text_hash: str
    cached: bool
    latency_ms: int
    storage_upload_ms: Optional[int]
    signed_url_ms: Optional[int]
    success: bool
    error: Optional[str]
    timestamp: str

    def log(self) -> None:
        """Print metrics as JSON for ingestion by logging tools."""
        print(json.dumps(self.__dict__))


def now_iso() -> str:
    """Return current time in ISO format."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
