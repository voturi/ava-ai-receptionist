"""
Deepgram Streaming Text-to-Speech Client.

Provides real-time audio synthesis using Deepgram Aura via WebSocket.
Streams audio chunks as they're generated for minimal latency.

Key features:
- Token-by-token streaming (send text as LLM generates)
- μ-law output for Twilio compatibility
- Flush mechanism to finalize audio generation

References:
- https://developers.deepgram.com/docs/tts-websocket
- https://developers.deepgram.com/docs/tts-streaming-feature-overview
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Optional

import websockets
from websockets.exceptions import ConnectionClosed

DEEPGRAM_TTS_WS_URL = "wss://api.deepgram.com/v1/speak"


@dataclass
class TTSConfig:
    """Configuration for Deepgram TTS."""

    model: str = "aura-asteria-en"  # Default voice
    sample_rate: int = 8000  # Twilio requires 8kHz
    encoding: str = "mulaw"  # Twilio requires μ-law
    container: str = "none"  # Raw audio, no container


# Available Aura voices (subset)
AURA_VOICES = {
    "asteria": "aura-asteria-en",  # American female (default)
    "luna": "aura-luna-en",  # American female
    "stella": "aura-stella-en",  # American female
    "athena": "aura-athena-en",  # British female
    "hera": "aura-hera-en",  # American female
    "orion": "aura-orion-en",  # American male
    "arcas": "aura-arcas-en",  # American male
    "perseus": "aura-perseus-en",  # American male
    "angus": "aura-angus-en",  # Irish male
    "orpheus": "aura-orpheus-en",  # American male
    "helios": "aura-helios-en",  # British male
    "zeus": "aura-zeus-en",  # American male
}


class DeepgramStreamingTTS:
    """
    Streaming text-to-speech using Deepgram Aura.

    Usage:
        async def on_audio(audio_bytes: bytes):
            # Send to Twilio
            await twilio_ws.send_audio(audio_bytes)

        async def on_complete():
            print("TTS complete")

        tts = DeepgramStreamingTTS(
            on_audio=on_audio,
            on_complete=on_complete,
        )
        await tts.connect()

        # Send text chunks as LLM generates them
        await tts.send_text("Hello, ")
        await tts.send_text("how can I help you today?")

        # Signal end of text
        await tts.flush()

        # When done
        await tts.close()
    """

    def __init__(
        self,
        on_audio: Callable[[bytes], Awaitable[None]],
        on_complete: Optional[Callable[[], Awaitable[None]]] = None,
        on_error: Optional[Callable[[str], Awaitable[None]]] = None,
        config: Optional[TTSConfig] = None,
    ):
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        if not self.api_key:
            raise ValueError("DEEPGRAM_API_KEY environment variable not set")

        self.on_audio = on_audio
        self.on_complete = on_complete
        self.on_error = on_error
        self.config = config or TTSConfig()

        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._connected = False
        self._closing = False
        self._flushing = False

        # Metrics
        self._text_chars_sent = 0
        self._audio_bytes_received = 0
        self._connected_at: Optional[datetime] = None
        self._first_audio_at: Optional[datetime] = None

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._connected and self._ws is not None and not self._ws.closed

    @property
    def time_to_first_audio_ms(self) -> Optional[float]:
        """Get time from connection to first audio byte."""
        if self._connected_at and self._first_audio_at:
            return (self._first_audio_at - self._connected_at).total_seconds() * 1000
        return None

    async def connect(self) -> None:
        """Establish WebSocket connection to Deepgram TTS."""
        if self._connected:
            return

        # Build URL with query parameters
        params = [
            f"model={self.config.model}",
            f"sample_rate={self.config.sample_rate}",
            f"encoding={self.config.encoding}",
            f"container={self.config.container}",
        ]
        url = f"{DEEPGRAM_TTS_WS_URL}?{'&'.join(params)}"

        try:
            self._ws = await websockets.connect(
                url,
                additional_headers={"Authorization": f"Token {self.api_key}"},
                ping_interval=20,
                ping_timeout=10,
            )
            self._connected = True
            self._connected_at = datetime.utcnow()

            # Start receive loop
            self._receive_task = asyncio.create_task(self._receive_loop())

            print(f"🔊 Deepgram TTS connected (model={self.config.model})")

        except Exception as e:
            print(f"❌ Failed to connect to Deepgram TTS: {e}")
            raise

    async def send_text(self, text: str) -> None:
        """
        Send text chunk for synthesis.

        Can be called multiple times to stream text as it's generated.
        Call flush() after all text is sent to finalize.
        """
        if not self.is_connected or not text:
            return

        try:
            message = {
                "type": "Speak",
                "text": text,
            }
            await self._ws.send(json.dumps(message))
            self._text_chars_sent += len(text)

        except ConnectionClosed:
            print("⚠️ TTS connection closed while sending text")
            self._connected = False
        except Exception as e:
            print(f"⚠️ Error sending text to TTS: {e}")

    async def flush(self) -> None:
        """
        Signal end of text input.

        Tells Deepgram to finalize synthesis and send remaining audio.
        """
        if not self.is_connected:
            return

        try:
            self._flushing = True
            message = {"type": "Flush"}
            await self._ws.send(json.dumps(message))
            print("🔊 TTS flush sent")

        except Exception as e:
            print(f"⚠️ Error flushing TTS: {e}")

    async def clear(self) -> None:
        """
        Clear pending audio buffer.

        Use for barge-in: stops current synthesis when user interrupts.
        """
        if not self.is_connected:
            return

        try:
            message = {"type": "Clear"}
            await self._ws.send(json.dumps(message))
            print("🔊 TTS buffer cleared")

        except Exception as e:
            print(f"⚠️ Error clearing TTS buffer: {e}")

    async def close(self) -> None:
        """Close the WebSocket connection gracefully."""
        if self._closing:
            return

        self._closing = True
        self._connected = False

        # Cancel receive task
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        # Close WebSocket
        if self._ws and not self._ws.closed:
            try:
                await self._ws.send(json.dumps({"type": "Close"}))
                await self._ws.close()
            except Exception as e:
                print(f"⚠️ Error closing TTS WebSocket: {e}")

        # Log metrics
        duration = (datetime.utcnow() - self._connected_at).total_seconds() if self._connected_at else 0
        ttfa = self.time_to_first_audio_ms
        print(
            f"🔊 Deepgram TTS closed ("
            f"duration={duration:.1f}s, "
            f"text={self._text_chars_sent} chars, "
            f"audio={self._audio_bytes_received/1024:.1f}KB, "
            f"TTFA={f'{ttfa:.0f}ms' if ttfa else 'N/A'})"
        )

    async def _receive_loop(self) -> None:
        """Process incoming messages from Deepgram."""
        try:
            async for message in self._ws:
                if self._closing:
                    break

                # Binary message = audio data
                if isinstance(message, bytes):
                    await self._handle_audio(message)

                # Text message = JSON metadata
                else:
                    try:
                        data = json.loads(message)
                        await self._handle_metadata(data)
                    except json.JSONDecodeError:
                        print(f"⚠️ Invalid JSON from Deepgram TTS: {message[:100]}")

        except ConnectionClosed as e:
            if not self._closing:
                print(f"🔊 Deepgram TTS connection closed: {e}")
            self._connected = False

        except asyncio.CancelledError:
            pass

        except Exception as e:
            print(f"❌ Error in TTS receive loop: {e}")
            self._connected = False

    async def _handle_audio(self, audio_bytes: bytes) -> None:
        """Handle incoming audio chunk."""
        # Track first audio for metrics
        if self._first_audio_at is None:
            self._first_audio_at = datetime.utcnow()
            ttfa = self.time_to_first_audio_ms
            print(f"⚡ TTS first audio received: {ttfa:.0f}ms")

        self._audio_bytes_received += len(audio_bytes)

        # Forward to callback
        await self.on_audio(audio_bytes)

    async def _handle_metadata(self, data: dict) -> None:
        """Handle metadata message from Deepgram."""
        msg_type = data.get("type")

        if msg_type == "Flushed":
            # All audio for current text has been sent
            print("🔊 TTS flush complete")
            if self.on_complete:
                await self.on_complete()

        elif msg_type == "Warning":
            warning = data.get("warn_msg", "Unknown warning")
            print(f"⚠️ Deepgram TTS warning: {warning}")

        elif msg_type == "Error":
            error = data.get("err_msg", "Unknown error")
            print(f"❌ Deepgram TTS error: {error}")
            if self.on_error:
                await self.on_error(error)

        elif msg_type == "Metadata":
            # Connection metadata
            request_id = data.get("request_id", "")
            print(f"🔊 TTS metadata (request_id={request_id})")


class TTSSession:
    """
    High-level TTS session for a single utterance.

    Manages connection lifecycle and provides simple API for speaking text.
    """

    def __init__(
        self,
        on_audio: Callable[[bytes], Awaitable[None]],
        voice: str = "asteria",
    ):
        self.on_audio = on_audio
        self.voice = AURA_VOICES.get(voice, AURA_VOICES["asteria"])
        self._tts: Optional[DeepgramStreamingTTS] = None
        self._complete_event = asyncio.Event()

    async def speak(self, text: str) -> None:
        """
        Speak the given text.

        Connects, sends text, flushes, and waits for completion.
        """
        self._complete_event.clear()

        self._tts = DeepgramStreamingTTS(
            on_audio=self.on_audio,
            on_complete=self._on_complete,
            config=TTSConfig(model=self.voice),
        )

        try:
            await self._tts.connect()
            await self._tts.send_text(text)
            await self._tts.flush()

            # Wait for flush complete (with timeout)
            try:
                await asyncio.wait_for(self._complete_event.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                print("⚠️ TTS completion timeout")

        finally:
            await self._tts.close()

    async def speak_streaming(
        self,
        text_stream: asyncio.Queue[str | None],
    ) -> None:
        """
        Speak text from a streaming source (e.g., LLM output).

        Reads text chunks from queue until None is received.
        """
        self._complete_event.clear()

        self._tts = DeepgramStreamingTTS(
            on_audio=self.on_audio,
            on_complete=self._on_complete,
            config=TTSConfig(model=self.voice),
        )

        try:
            await self._tts.connect()

            # Stream text chunks
            while True:
                text = await text_stream.get()
                if text is None:
                    break
                await self._tts.send_text(text)

            await self._tts.flush()

            # Wait for completion
            try:
                await asyncio.wait_for(self._complete_event.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                print("⚠️ TTS completion timeout")

        finally:
            await self._tts.close()

    async def _on_complete(self) -> None:
        """Handle TTS completion."""
        self._complete_event.set()
