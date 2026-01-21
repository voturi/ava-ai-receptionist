"""
Deepgram Streaming Speech-to-Text Client.

Provides real-time transcription using Deepgram Nova via WebSocket.
Optimized for low latency with:
- Interim results for faster feedback
- Utterance end detection (VAD)
- Configurable endpointing for EagerEndOfTurn

References:
- https://developers.deepgram.com/docs/getting-started-with-live-streaming-audio
- https://developers.deepgram.com/docs/understanding-end-of-speech-detection
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable, Optional

import websockets
from websockets.exceptions import ConnectionClosed
from websockets.protocol import State

DEEPGRAM_STT_WS_URL = "wss://api.deepgram.com/v1/listen"

# Detect websockets version for header parameter compatibility
# v10-12 uses extra_headers, v13+ uses additional_headers
import inspect
_ws_connect_params = inspect.signature(websockets.connect).parameters
WS_HEADERS_PARAM = "additional_headers" if "additional_headers" in _ws_connect_params else "extra_headers"
print(f"🔧 websockets {websockets.__version__} using {WS_HEADERS_PARAM}")


@dataclass
class STTConfig:
    """Configuration for Deepgram STT."""

    model: str = "nova-2"
    language: str = "en-AU"
    sample_rate: int = 8000
    encoding: str = "mulaw"
    channels: int = 1
    punctuate: bool = True
    interim_results: bool = True
    utterance_end_ms: int = 1000  # Silence duration to trigger utterance end
    vad_events: bool = True
    endpointing: int = 300  # EagerEndOfTurn: 300ms silence triggers early


@dataclass
class TranscriptResult:
    """Result from STT transcription."""

    text: str
    is_final: bool
    confidence: float = 0.0
    start_time: float = 0.0
    end_time: float = 0.0
    words: list = field(default_factory=list)


class DeepgramStreamingSTT:
    """
    Streaming speech-to-text using Deepgram Nova.

    Usage:
        async def on_transcript(result: TranscriptResult):
            print(f"[{'FINAL' if result.is_final else 'PARTIAL'}] {result.text}")

        async def on_utterance_end():
            print("User stopped speaking")

        stt = DeepgramStreamingSTT(
            on_transcript=on_transcript,
            on_utterance_end=on_utterance_end,
        )
        await stt.connect()

        # Send audio chunks (μ-law encoded, 8kHz)
        await stt.send_audio(audio_bytes)

        # When done
        await stt.close()
    """

    def __init__(
        self,
        on_transcript: Callable[[TranscriptResult], Awaitable[None]],
        on_utterance_end: Optional[Callable[[], Awaitable[None]]] = None,
        on_speech_started: Optional[Callable[[], Awaitable[None]]] = None,
        config: Optional[STTConfig] = None,
    ):
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        if not self.api_key:
            raise ValueError("DEEPGRAM_API_KEY environment variable not set")

        self.on_transcript = on_transcript
        self.on_utterance_end = on_utterance_end
        self.on_speech_started = on_speech_started
        self.config = config or STTConfig()

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._keepalive_task: Optional[asyncio.Task] = None
        self._connected = False
        self._closing = False

        # Metrics
        self._audio_bytes_sent = 0
        self._transcripts_received = 0
        self._connected_at: Optional[datetime] = None

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        if not self._connected or self._ws is None:
            return False
        try:
            return self._ws.state == State.OPEN
        except Exception:
            return False

    async def connect(self) -> None:
        """Establish WebSocket connection to Deepgram."""
        if self._connected:
            return

        # Build URL with query parameters
        params = [
            f"model={self.config.model}",
            f"language={self.config.language}",
            f"encoding={self.config.encoding}",
            f"sample_rate={self.config.sample_rate}",
            f"channels={self.config.channels}",
            f"punctuate={str(self.config.punctuate).lower()}",
            f"interim_results={str(self.config.interim_results).lower()}",
            f"utterance_end_ms={self.config.utterance_end_ms}",
            f"vad_events={str(self.config.vad_events).lower()}",
            f"endpointing={self.config.endpointing}",
        ]
        url = f"{DEEPGRAM_STT_WS_URL}?{'&'.join(params)}"

        try:
            # Use version-appropriate header parameter
            connect_kwargs = {
                WS_HEADERS_PARAM: {"Authorization": f"Token {self.api_key}"},
                "ping_interval": 20,
                "ping_timeout": 10,
            }
            self._ws = await websockets.connect(url, **connect_kwargs)
            self._connected = True
            self._connected_at = datetime.utcnow()

            # Start receive loop
            self._receive_task = asyncio.create_task(self._receive_loop())

            # Start keepalive loop
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())

            print(f"🎤 Deepgram STT connected (model={self.config.model})")

        except Exception as e:
            print(f"❌ Failed to connect to Deepgram STT: {e}")
            raise

    async def send_audio(self, audio_bytes: bytes) -> None:
        """
        Send audio chunk to Deepgram for transcription.

        Audio must match the configured encoding and sample rate.
        For Twilio Media Streams: μ-law, 8kHz, mono.
        """
        if not self.is_connected:
            return

        try:
            await self._ws.send(audio_bytes)
            self._audio_bytes_sent += len(audio_bytes)
        except ConnectionClosed:
            print("⚠️ STT connection closed while sending audio")
            self._connected = False
        except Exception as e:
            print(f"⚠️ Error sending audio to STT: {e}")

    async def close(self) -> None:
        """Close the WebSocket connection gracefully."""
        if self._closing:
            return

        self._closing = True
        self._connected = False

        # Cancel tasks
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass

        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        # Close WebSocket
        if self._ws and self._ws.state == State.OPEN:
            try:
                # Send close message to finalize transcription
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                await self._ws.close()
            except Exception as e:
                print(f"⚠️ Error closing STT WebSocket: {e}")

        # Log metrics
        duration = (datetime.utcnow() - self._connected_at).total_seconds() if self._connected_at else 0
        print(f"🎤 Deepgram STT closed (duration={duration:.1f}s, audio={self._audio_bytes_sent/1024:.1f}KB, transcripts={self._transcripts_received})")

    async def _receive_loop(self) -> None:
        """Process incoming messages from Deepgram."""
        try:
            async for message in self._ws:
                if self._closing:
                    break

                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    print(f"⚠️ Invalid JSON from Deepgram: {message[:100]}")

        except ConnectionClosed as e:
            if not self._closing:
                print(f"🎤 Deepgram STT connection closed: {e}")
            self._connected = False

        except asyncio.CancelledError:
            pass

        except Exception as e:
            print(f"❌ Error in STT receive loop: {e}")
            self._connected = False

    async def _handle_message(self, data: dict) -> None:
        """Handle a message from Deepgram."""
        msg_type = data.get("type")

        if msg_type == "Results":
            # Transcription result
            channel = data.get("channel", {})
            alternatives = channel.get("alternatives", [])

            if alternatives:
                alt = alternatives[0]
                transcript = alt.get("transcript", "")

                if transcript:
                    self._transcripts_received += 1

                    result = TranscriptResult(
                        text=transcript,
                        is_final=data.get("is_final", False),
                        confidence=alt.get("confidence", 0.0),
                        start_time=data.get("start", 0.0),
                        end_time=data.get("start", 0.0) + data.get("duration", 0.0),
                        words=alt.get("words", []),
                    )

                    await self.on_transcript(result)

        elif msg_type == "UtteranceEnd":
            # User stopped speaking
            if self.on_utterance_end:
                await self.on_utterance_end()

        elif msg_type == "SpeechStarted":
            # User started speaking
            if self.on_speech_started:
                await self.on_speech_started()

        elif msg_type == "Metadata":
            # Connection metadata
            request_id = data.get("request_id", "")
            print(f"🎤 STT metadata received (request_id={request_id})")

        elif msg_type == "Error":
            # Error from Deepgram
            error_msg = data.get("message", "Unknown error")
            print(f"❌ Deepgram STT error: {error_msg}")

    async def _keepalive_loop(self) -> None:
        """
        Send periodic keepalive messages.

        Deepgram may close idle connections after 10 seconds of no audio.
        """
        try:
            while self._connected and not self._closing:
                await asyncio.sleep(8)

                if self.is_connected:
                    try:
                        # Send empty keepalive
                        await self._ws.send(json.dumps({"type": "KeepAlive"}))
                    except Exception:
                        pass

        except asyncio.CancelledError:
            pass
