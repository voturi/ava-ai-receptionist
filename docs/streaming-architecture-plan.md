# Streaming-First Cascaded Architecture Plan

> **Goal:** Achieve <800ms end-to-end latency with production-grade streaming
> **Target:** Replace webhook-based flow with bidirectional WebSocket architecture
> **Philosophy:** Clean Enough (90% clean for voice critical path)

---

## Executive Summary

This plan upgrades the digital receptionist from HTTP webhooks to a **full-duplex streaming architecture** using Twilio Media Streams. The goal is to reduce perceived latency from ~2 seconds (current filler-based approach) to **<800ms end-to-end**.

### Provider Recommendation: Deepgram

After evaluating both options, **Deepgram** is recommended for production:

| Criteria | Deepgram | ElevenLabs |
|----------|----------|------------|
| **TTS Latency** | ~745ms total, 70% savings with streaming | 75ms TTFB (Flash v2.5), but higher total |
| **WebSocket Speed** | 3x faster than ElevenLabs (per Deepgram benchmarks) | Good, but slower |
| **STT Integration** | Nova 2 with <300ms first-word latency | Scribe v2: 150ms (separate product) |
| **Unified Platform** | Single vendor for STT + TTS | Need separate STT provider |
| **Existing Integration** | Already integrated | Would need new integration |
| **Voice Quality** | Good (Aura voices) | Excellent (more expressive) |
| **Cost** | Lower | Higher (~2-3x) |

**Recommendation:** Start with Deepgram for unified STT+TTS. Add ElevenLabs as a premium voice option later if customers request higher quality voices.

---

## Architecture Comparison

### Current: Webhook-Based (HTTP)

```
┌──────────┐    HTTP     ┌─────────┐    HTTP    ┌─────────┐
│  Twilio  │◄──────────► │ Backend │◄──────────►│ OpenAI  │
│  Voice   │  Webhooks   │ FastAPI │   REST     │  GPT-4  │
└──────────┘             └─────────┘            └─────────┘
                              │
                              │ HTTP
                              ▼
                         ┌─────────┐
                         │Deepgram │
                         │  TTS    │
                         └─────────┘

Flow:
1. User speaks → Twilio STT → HTTP webhook (500ms)
2. Backend receives text → AI processing (500-1500ms)
3. TTS synthesis → Upload → Get URL (800-2000ms)
4. Return TwiML → Twilio plays audio

Total: 1.8 - 4.0 seconds
With filler: ~0.5s perceived (filler), ~2s to real response
```

### Target: Streaming (WebSocket)

```
┌──────────┐  WebSocket  ┌─────────┐  WebSocket ┌─────────┐
│  Twilio  │◄═══════════►│ Backend │◄═══════════►│Deepgram │
│  Media   │ Bidirectional│ FastAPI │   STT      │  Nova   │
│ Streams  │    μlaw     │   WS    │            └─────────┘
└──────────┘             │ Server  │
                         │         │  WebSocket ┌─────────┐
                         │         │◄═══════════►│Deepgram │
                         │         │    TTS     │  Aura   │
                         │         │            └─────────┘
                         │         │
                         │         │  Streaming ┌─────────┐
                         │         │◄═══════════►│ OpenAI  │
                         │         │    LLM     │  GPT-4  │
                         └─────────┘            └─────────┘

Flow (fully pipelined):
1. User speaks → Audio chunks stream to Deepgram STT
2. Partial transcripts stream to LLM (speculative processing)
3. LLM tokens stream to Deepgram TTS
4. Audio chunks stream back to Twilio (playback starts immediately)

Total: <800ms to first audio byte
```

---

## Latency Breakdown Target

| Component | Current | Target | Method |
|-----------|---------|--------|--------|
| **Audio to STT** | 500ms (webhook batch) | <300ms | Streaming to Deepgram Nova |
| **STT to LLM** | 100ms | <50ms | EagerEndOfTurn detection |
| **LLM Processing** | 500-1500ms | 300-500ms | Token streaming + smaller model |
| **LLM to TTS** | 100ms | <50ms | Direct WebSocket pipe |
| **TTS Synthesis** | 800-2000ms | <200ms | Streaming audio generation |
| **Audio Playback Start** | Wait for full audio | Immediate | Chunk-based streaming |
| **Total** | 1.8-4.0s | <800ms | Pipelined architecture |

---

## Implementation Phases

### Phase 1: WebSocket Server Infrastructure (Week 1)

**Goal:** Set up bidirectional WebSocket server for Twilio Media Streams

#### 1.1 Add WebSocket Dependencies

```bash
# Add to requirements.txt
websockets>=12.0
python-multipart>=0.0.6
```

#### 1.2 Create WebSocket Handler

**File:** `backend/app/api/v1/media_stream.py`

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream
import base64
import json
import asyncio

router = APIRouter()

# Active call sessions
sessions: dict[str, "CallSession"] = {}


@router.post("/incoming/{business_id}")
async def incoming_call_stream(business_id: str, request: Request):
    """
    Twilio webhook that initiates Media Stream connection.
    Returns TwiML that connects to our WebSocket server.
    """
    form = await request.form()
    call_sid = form.get("CallSid")

    # Get WebSocket URL (same host, /ws path)
    host = request.headers.get("host", "localhost:8000")
    ws_url = f"wss://{host}/ws/media/{business_id}/{call_sid}"

    response = VoiceResponse()
    connect = Connect()
    stream = Stream(url=ws_url)
    stream.parameter(name="business_id", value=business_id)
    connect.append(stream)
    response.append(connect)

    return Response(content=str(response), media_type="application/xml")


@router.websocket("/ws/media/{business_id}/{call_sid}")
async def media_stream_handler(
    websocket: WebSocket,
    business_id: str,
    call_sid: str,
):
    """
    Bidirectional WebSocket handler for Twilio Media Streams.

    Receives: Audio chunks from caller (μ-law encoded)
    Sends: Audio chunks to play to caller (μ-law encoded)
    """
    await websocket.accept()

    session = CallSession(
        call_sid=call_sid,
        business_id=business_id,
        websocket=websocket,
    )
    sessions[call_sid] = session

    try:
        await session.initialize()

        # Main message loop
        async for message in websocket.iter_text():
            await session.handle_twilio_message(json.loads(message))

    except WebSocketDisconnect:
        print(f"📞 Call {call_sid} disconnected")
    finally:
        await session.cleanup()
        sessions.pop(call_sid, None)
```

#### 1.3 Create Call Session Manager

**File:** `backend/app/services/call_session.py`

```python
from dataclasses import dataclass, field
from fastapi import WebSocket
import asyncio
import base64
from typing import Optional
from datetime import datetime


@dataclass
class CallSession:
    """Manages state for a single streaming call."""

    call_sid: str
    business_id: str
    websocket: WebSocket

    # Stream metadata (set on 'start' message)
    stream_sid: Optional[str] = None
    audio_track: str = "inbound"

    # STT connection
    stt_ws: Optional[any] = None

    # TTS connection
    tts_ws: Optional[any] = None

    # Conversation state
    conversation_history: list = field(default_factory=list)
    current_transcript: str = ""
    is_speaking: bool = False

    # Timing metrics
    started_at: Optional[datetime] = None
    last_audio_at: Optional[datetime] = None

    async def initialize(self):
        """Set up STT and TTS WebSocket connections."""
        self.started_at = datetime.utcnow()

        # Initialize Deepgram STT WebSocket
        self.stt_ws = await self._connect_deepgram_stt()

        # Initialize Deepgram TTS WebSocket
        self.tts_ws = await self._connect_deepgram_tts()

        # Play greeting
        await self._play_greeting()

    async def handle_twilio_message(self, message: dict):
        """Process incoming Twilio WebSocket message."""
        event = message.get("event")

        if event == "connected":
            print(f"🔌 Twilio connected: {self.call_sid}")

        elif event == "start":
            self.stream_sid = message["start"]["streamSid"]
            self.audio_track = message["start"].get("track", "inbound")
            print(f"🎙️ Stream started: {self.stream_sid}")

        elif event == "media":
            # Forward audio to STT
            audio_payload = message["media"]["payload"]  # base64 μ-law
            await self._forward_to_stt(audio_payload)

        elif event == "stop":
            print(f"⏹️ Stream stopped: {self.call_sid}")

    async def send_audio_to_caller(self, audio_bytes: bytes):
        """Send audio chunk to Twilio for playback."""
        payload = base64.b64encode(audio_bytes).decode("utf-8")
        await self.websocket.send_json({
            "event": "media",
            "streamSid": self.stream_sid,
            "media": {
                "payload": payload,
            }
        })

    async def cleanup(self):
        """Clean up resources when call ends."""
        if self.stt_ws:
            await self.stt_ws.close()
        if self.tts_ws:
            await self.tts_ws.close()
```

---

### Phase 2: Deepgram Streaming STT (Week 1-2)

**Goal:** Replace Twilio's `<Gather>` with Deepgram Nova streaming STT

#### 2.1 Create Deepgram STT Client

**File:** `backend/app/integrations/stt/deepgram_streaming.py`

```python
import websockets
import json
import os
from typing import Callable, Awaitable

DEEPGRAM_STT_WS = "wss://api.deepgram.com/v1/listen"


class DeepgramStreamingSTT:
    """Streaming speech-to-text using Deepgram Nova."""

    def __init__(
        self,
        on_transcript: Callable[[str, bool], Awaitable[None]],
        on_utterance_end: Callable[[], Awaitable[None]],
    ):
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        self.on_transcript = on_transcript  # (text, is_final)
        self.on_utterance_end = on_utterance_end
        self.ws = None
        self._receive_task = None

    async def connect(self, sample_rate: int = 8000, encoding: str = "mulaw"):
        """Establish WebSocket connection to Deepgram."""
        url = (
            f"{DEEPGRAM_STT_WS}"
            f"?model=nova-2"
            f"&language=en-AU"
            f"&encoding={encoding}"
            f"&sample_rate={sample_rate}"
            f"&channels=1"
            f"&punctuate=true"
            f"&interim_results=true"
            f"&utterance_end_ms=1000"
            f"&vad_events=true"
            f"&endpointing=300"  # EagerEndOfTurn: 300ms silence
        )

        self.ws = await websockets.connect(
            url,
            extra_headers={"Authorization": f"Token {self.api_key}"},
        )

        # Start receiving task
        self._receive_task = asyncio.create_task(self._receive_loop())

        print("🎤 Deepgram STT connected")

    async def send_audio(self, audio_bytes: bytes):
        """Send audio chunk to Deepgram."""
        if self.ws and self.ws.open:
            await self.ws.send(audio_bytes)

    async def _receive_loop(self):
        """Process incoming transcription results."""
        try:
            async for message in self.ws:
                data = json.loads(message)

                if data.get("type") == "Results":
                    channel = data.get("channel", {})
                    alternatives = channel.get("alternatives", [])

                    if alternatives:
                        transcript = alternatives[0].get("transcript", "")
                        is_final = data.get("is_final", False)

                        if transcript:
                            await self.on_transcript(transcript, is_final)

                elif data.get("type") == "UtteranceEnd":
                    await self.on_utterance_end()

        except websockets.exceptions.ConnectionClosed:
            print("🎤 Deepgram STT connection closed")

    async def close(self):
        """Close the WebSocket connection."""
        if self._receive_task:
            self._receive_task.cancel()
        if self.ws:
            await self.ws.close()
```

#### 2.2 Integrate STT with Call Session

Update `CallSession` to use streaming STT:

```python
async def _connect_deepgram_stt(self):
    """Connect to Deepgram streaming STT."""
    stt = DeepgramStreamingSTT(
        on_transcript=self._handle_transcript,
        on_utterance_end=self._handle_utterance_end,
    )
    await stt.connect(sample_rate=8000, encoding="mulaw")
    return stt

async def _handle_transcript(self, text: str, is_final: bool):
    """Handle incoming transcript from STT."""
    self.current_transcript = text

    if is_final:
        print(f"🎤 [FINAL] {text}")
        # Start LLM processing immediately
        asyncio.create_task(self._process_with_llm(text))
    else:
        print(f"🎤 [PARTIAL] {text}")
        # Could start speculative LLM processing here

async def _handle_utterance_end(self):
    """Handle end of user utterance."""
    if self.current_transcript:
        # User stopped speaking - finalize and process
        print(f"🛑 Utterance end: {self.current_transcript}")
        self.current_transcript = ""

async def _forward_to_stt(self, base64_audio: str):
    """Forward Twilio audio to Deepgram STT."""
    audio_bytes = base64.b64decode(base64_audio)
    await self.stt_ws.send_audio(audio_bytes)
```

---

### Phase 3: Deepgram Streaming TTS (Week 2)

**Goal:** Stream audio tokens directly to Twilio as they're generated

#### 3.1 Create Deepgram TTS WebSocket Client

**File:** `backend/app/integrations/tts/deepgram_streaming.py`

```python
import websockets
import json
import os
from typing import Callable, Awaitable

DEEPGRAM_TTS_WS = "wss://api.deepgram.com/v1/speak"


class DeepgramStreamingTTS:
    """Streaming text-to-speech using Deepgram Aura."""

    def __init__(
        self,
        on_audio: Callable[[bytes], Awaitable[None]],
        voice: str = "aura-asteria-en",
    ):
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        self.on_audio = on_audio
        self.voice = voice
        self.ws = None
        self._receive_task = None

    async def connect(self, sample_rate: int = 8000, encoding: str = "mulaw"):
        """Establish WebSocket connection to Deepgram TTS."""
        url = (
            f"{DEEPGRAM_TTS_WS}"
            f"?model={self.voice}"
            f"&encoding={encoding}"
            f"&sample_rate={sample_rate}"
            f"&container=none"
        )

        self.ws = await websockets.connect(
            url,
            extra_headers={"Authorization": f"Token {self.api_key}"},
        )

        # Start receiving task
        self._receive_task = asyncio.create_task(self._receive_loop())

        print("🔊 Deepgram TTS connected")

    async def send_text(self, text: str):
        """Send text chunk to synthesize."""
        if self.ws and self.ws.open:
            await self.ws.send(json.dumps({
                "type": "Speak",
                "text": text,
            }))

    async def flush(self):
        """Signal end of text input."""
        if self.ws and self.ws.open:
            await self.ws.send(json.dumps({
                "type": "Flush",
            }))

    async def _receive_loop(self):
        """Process incoming audio chunks."""
        try:
            async for message in self.ws:
                if isinstance(message, bytes):
                    # Raw audio data - forward to caller
                    await self.on_audio(message)
                else:
                    # JSON metadata
                    data = json.loads(message)
                    if data.get("type") == "Flushed":
                        print("🔊 TTS flush complete")

        except websockets.exceptions.ConnectionClosed:
            print("🔊 Deepgram TTS connection closed")

    async def close(self):
        """Close the WebSocket connection."""
        if self._receive_task:
            self._receive_task.cancel()
        if self.ws:
            await self.ws.close()
```

#### 3.2 Integrate TTS with Call Session

```python
async def _connect_deepgram_tts(self):
    """Connect to Deepgram streaming TTS."""
    tts = DeepgramStreamingTTS(
        on_audio=self._handle_tts_audio,
        voice="aura-asteria-en",  # Australian-like voice
    )
    await tts.connect(sample_rate=8000, encoding="mulaw")
    return tts

async def _handle_tts_audio(self, audio_bytes: bytes):
    """Forward TTS audio to Twilio for playback."""
    await self.send_audio_to_caller(audio_bytes)
```

---

### Phase 4: Streaming LLM Integration (Week 2-3)

**Goal:** Stream LLM tokens directly to TTS as they're generated

#### 4.1 OpenAI Streaming Integration

**File:** `backend/app/services/streaming_ai_service.py`

```python
from openai import AsyncOpenAI
import os
from typing import AsyncGenerator


class StreamingAIService:
    """AI service with streaming token output."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = "gpt-4o-mini"  # Faster than gpt-4-turbo

    async def get_streaming_response(
        self,
        user_message: str,
        conversation_history: list,
        business_name: str,
    ) -> AsyncGenerator[str, None]:
        """
        Stream AI response token by token.

        Yields text chunks as they're generated.
        """
        messages = [
            {"role": "system", "content": self._get_system_prompt(business_name)},
            *conversation_history,
            {"role": "user", "content": user_message},
        ]

        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=150,
            temperature=0.7,
            stream=True,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    def _get_system_prompt(self, business_name: str) -> str:
        return f"""You are Sarah, the AI receptionist for {business_name}.

YOUR PERSONALITY:
- Warm, friendly, and professional
- Use Australian expressions: "no worries", "lovely", "arvo"
- Keep responses SHORT (15-20 words max)
- Sound natural, not robotic

BOOKING PROCESS:
1. Ask what service they need
2. Ask preferred day and time
3. Get their name
4. Confirm details
5. Complete booking

Keep it conversational and brief!"""


streaming_ai_service = StreamingAIService()
```

#### 4.2 Connect LLM to TTS Pipeline

Update `CallSession`:

```python
async def _process_with_llm(self, user_text: str):
    """Process user input with streaming LLM → TTS pipeline."""

    # Add to conversation history
    self.conversation_history.append({
        "role": "user",
        "content": user_text,
    })

    # Track timing
    start_time = datetime.utcnow()
    first_audio_sent = False
    full_response = ""

    # Stream LLM → TTS
    buffer = ""
    async for token in streaming_ai_service.get_streaming_response(
        user_message=user_text,
        conversation_history=self.conversation_history[:-1],
        business_name=self.business_name,
    ):
        full_response += token
        buffer += token

        # Send to TTS when we have a natural break
        # (period, comma, or enough characters)
        if self._should_flush_to_tts(buffer):
            await self.tts_ws.send_text(buffer)
            buffer = ""

            if not first_audio_sent:
                latency = (datetime.utcnow() - start_time).total_seconds()
                print(f"⚡ Time to first audio: {latency*1000:.0f}ms")
                first_audio_sent = True

    # Send remaining buffer
    if buffer:
        await self.tts_ws.send_text(buffer)

    # Signal end of text
    await self.tts_ws.flush()

    # Update conversation history
    self.conversation_history.append({
        "role": "assistant",
        "content": full_response,
    })

    print(f"🤖 AI: {full_response}")

def _should_flush_to_tts(self, buffer: str) -> bool:
    """Determine if we should send buffer to TTS."""
    # Send on sentence boundaries
    if buffer.rstrip().endswith((".", "!", "?", ",")):
        return len(buffer) >= 10
    # Or if buffer is getting long
    return len(buffer) >= 50
```

---

### Phase 5: Barge-In Detection (Week 3)

**Goal:** Allow users to interrupt AI while it's speaking

#### 5.1 Implement Barge-In

```python
@dataclass
class CallSession:
    # ... existing fields ...
    is_ai_speaking: bool = False

    async def _handle_tts_audio(self, audio_bytes: bytes):
        """Forward TTS audio to Twilio for playback."""
        self.is_ai_speaking = True
        await self.send_audio_to_caller(audio_bytes)

    async def _handle_transcript(self, text: str, is_final: bool):
        """Handle incoming transcript - with barge-in support."""

        # If user speaks while AI is speaking = barge-in
        if self.is_ai_speaking and len(text) > 5:
            print(f"🛑 BARGE-IN detected: {text}")
            await self._stop_current_playback()
            self.is_ai_speaking = False

        self.current_transcript = text

        if is_final:
            asyncio.create_task(self._process_with_llm(text))

    async def _stop_current_playback(self):
        """Clear Twilio's audio buffer."""
        await self.websocket.send_json({
            "event": "clear",
            "streamSid": self.stream_sid,
        })
```

---

### Phase 6: Production Hardening (Week 3-4)

#### 6.1 Add Error Handling and Reconnection

```python
class ResilientWebSocketConnection:
    """WebSocket connection with automatic reconnection."""

    def __init__(self, url: str, headers: dict, max_retries: int = 3):
        self.url = url
        self.headers = headers
        self.max_retries = max_retries
        self.ws = None
        self.retry_count = 0

    async def connect(self):
        """Connect with retry logic."""
        while self.retry_count < self.max_retries:
            try:
                self.ws = await websockets.connect(
                    self.url,
                    extra_headers=self.headers,
                    ping_interval=20,
                    ping_timeout=10,
                )
                self.retry_count = 0
                return
            except Exception as e:
                self.retry_count += 1
                wait_time = min(2 ** self.retry_count, 10)
                print(f"⚠️ Connection failed, retrying in {wait_time}s: {e}")
                await asyncio.sleep(wait_time)

        raise ConnectionError(f"Failed to connect after {self.max_retries} retries")
```

#### 6.2 Add Metrics and Monitoring

```python
from dataclasses import dataclass
from typing import Optional
import time


@dataclass
class CallMetrics:
    """Track latency and quality metrics for a call."""

    call_sid: str
    stt_first_result_ms: Optional[float] = None
    llm_first_token_ms: Optional[float] = None
    tts_first_audio_ms: Optional[float] = None
    total_latency_ms: Optional[float] = None
    barge_in_count: int = 0
    stt_reconnects: int = 0
    tts_reconnects: int = 0

    def log(self):
        """Log metrics for monitoring."""
        print(f"""
        📊 CALL METRICS: {self.call_sid}
        ───────────────────────────────
        STT First Result: {self.stt_first_result_ms:.0f}ms
        LLM First Token:  {self.llm_first_token_ms:.0f}ms
        TTS First Audio:  {self.tts_first_audio_ms:.0f}ms
        Total Latency:    {self.total_latency_ms:.0f}ms
        Barge-ins:        {self.barge_in_count}
        ───────────────────────────────
        """)
```

---

## Migration Strategy

### Step 1: Parallel Deployment

Run both systems simultaneously:

```python
@router.post("/incoming/{business_id}")
async def incoming_call(business_id: str, request: Request):
    """Route to streaming or webhook based on feature flag."""
    business = await get_business(business_id)

    if business.ai_config.get("use_streaming", False):
        return await incoming_call_stream(business_id, request)
    else:
        return await handle_incoming_call(business_id, request)
```

### Step 2: Gradual Rollout

1. **Week 1:** Enable for internal test numbers
2. **Week 2:** Enable for 1-2 beta businesses
3. **Week 3:** Enable for 10% of businesses
4. **Week 4:** Full rollout

### Step 3: Fallback

If streaming fails, automatically fall back to webhook:

```python
async def media_stream_handler(websocket: WebSocket, ...):
    try:
        # ... streaming logic ...
    except Exception as e:
        print(f"❌ Streaming failed, falling back to webhook: {e}")
        # Trigger callback to use webhook flow
        await trigger_webhook_fallback(call_sid, business_id)
```

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `app/api/v1/media_stream.py` | Create | WebSocket handler for Twilio Media Streams |
| `app/services/call_session.py` | Create | Call session state management |
| `app/integrations/stt/deepgram_streaming.py` | Create | Streaming STT client |
| `app/integrations/tts/deepgram_streaming.py` | Create | Streaming TTS client |
| `app/services/streaming_ai_service.py` | Create | Streaming LLM integration |
| `app/main.py` | Modify | Add WebSocket routes |
| `requirements.txt` | Modify | Add websockets dependency |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| WebSocket disconnections | Automatic reconnection with exponential backoff |
| High latency spikes | Fallback to cached filler + webhook |
| Audio quality issues | Test μ-law encoding thoroughly |
| Deepgram outage | ElevenLabs as backup TTS provider |
| Memory leaks | Strict session cleanup on disconnect |
| Cost overruns | Monitor streaming usage, set alerts |

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Time to first audio | 500ms (filler) | <300ms (real response) |
| End-to-end latency | 1.8-2.0s | <800ms |
| Perceived latency | ~500ms (with filler) | <500ms (no filler needed) |
| Barge-in support | No | Yes |
| Connection stability | N/A | >99.5% |

---

## Cost Analysis

### Current (Webhook-based)

- Twilio: ~$0.013/minute (voice)
- Deepgram TTS: ~$0.015/1000 chars
- OpenAI: ~$0.002/request
- **Total:** ~$0.03/minute

### Streaming

- Twilio Media Streams: ~$0.014/minute (slight increase)
- Deepgram STT: ~$0.0043/minute
- Deepgram TTS: ~$0.015/1000 chars
- OpenAI: ~$0.002/request
- **Total:** ~$0.035/minute (+17%)

**Worth it:** 60% latency reduction justifies 17% cost increase.

---

## Alternative: ElevenLabs Premium Option

For businesses wanting premium voice quality, offer ElevenLabs as an upgrade:

```python
# In voice config
{
    "tts_provider": "elevenlabs",  # or "deepgram"
    "tts_model": "eleven_flash_v2_5",  # 75ms TTFB
    "voice_id": "custom_cloned_voice",
}
```

**ElevenLabs Benefits:**
- More expressive, natural voices
- Voice cloning for brand consistency
- Higher customer satisfaction scores

**ElevenLabs Drawbacks:**
- 2-3x more expensive
- Separate integration from STT
- Slightly higher latency than Deepgram

---

## Conclusion

The streaming-first architecture with **Deepgram** provides the best balance of:

1. **Latency:** <800ms end-to-end
2. **Cost:** Marginal increase from current
3. **Simplicity:** Single vendor for STT + TTS
4. **Reliability:** Already integrated, proven stable

Start with Deepgram, add ElevenLabs as a premium option later if customer demand warrants.

---

*Last updated: January 21, 2026*
