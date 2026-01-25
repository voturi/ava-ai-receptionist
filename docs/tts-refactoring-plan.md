# TTS Refactoring Plan: Streaming-First Improvements

> **Goal:** Achieve <2 second latency with incremental improvements
> **Focus:** Streaming TTS playback + Better filler audio
> **Philosophy:** Clean Enough (70-90% clean for voice critical path)

---

## Executive Summary

This plan addresses the latency gap between the target "Streaming-First Cascaded Architecture" and the current webhook-based implementation. Rather than a full rewrite to Twilio Media Streams, we achieve acceptable latency (<2s) through:

1. **Proactive filler audio** - Play immediately, don't wait for TTS
2. **Parallel TTS synthesis** - Start synthesis before returning response
3. **Optimized Deepgram provider** - Connection pooling, reduced round-trips

---

## Gap Analysis

| Aspect | Target (Streaming-First) | Current Implementation |
|--------|-------------------------|------------------------|
| **Audio Transport** | Twilio Media Streams (WebSocket) | Twilio Webhooks (HTTP) |
| **STT** | Streaming to Deepgram Nova | Twilio's `<Gather>` |
| **TTS** | Streaming playback as tokens generate | Blocking - full audio before play |
| **Latency Target** | <800ms end-to-end | 1.6 - 3.8 seconds |
| **Filler Audio** | Proactive during processing | Reactive on timeout only |

---

## Current Flow (Problem)

```r
User speaks → Twilio STT → Webhook receives text
    → AI generates response (~500-1500ms)
    → TTS synthesis (~800-2000ms)
    → Upload to Supabase (~200ms)
    → Get signed URL (~100ms)
    → Return TwiML with <Play>

Total: 1.6 - 3.8 seconds of SILENCE
```

The `_enqueue_tts_response` function (`voice.py:631-659`) tries to hide latency with a "thinking" redirect, but it's **reactive** (only triggers on timeout) rather than **proactive**.

---

## Proposed Flow (Solution)

```
User speaks → Twilio STT → Webhook receives text
    → AI generates response (~500-1500ms)
    → IMMEDIATELY return TwiML:
        1. <Play> verbal filler ("Let me check that for you...")
        2. <Redirect> to /voice/tts-ready/{...}

    → Meanwhile (async): TTS synthesis happening in background

    → /voice/tts-ready endpoint:
        → Await TTS task (up to 6-8 seconds - user is hearing filler)
        → Return <Play> with TTS audio URL

Total perceived silence: ~0ms (filler plays immediately)
```

---

## Implementation Phases

### Phase 1: Filler Audio Infrastructure

**Estimated effort:** 1-2 hours

#### 1.1 Add filler generation function

**File:** `backend/app/integrations/tts/greeting.py`

```python
async def generate_filler_audio(
    business_id: str,
    voice: VoiceConfig,
) -> dict[str, AudioResult]:
    """Generate and store filler audio clips for a business."""
    fillers = {
        "thinking": "Let me check that for you.",
    }
    results = {}
    provider = resolve_provider(voice)
    for key, text in fillers.items():
        results[key] = await provider.synthesize(text, voice)
    return results
```

#### 1.2 Update business config schema

Add `filler_audio_url` to `ai_config.voice`:

```json
{
  "voice": {
    "provider": "deepgram",
    "voice_id": "aura-asteria-en-au",
    "greeting_audio_url": "https://...",
    "filler_audio_url": "https://...",
    "thinking_audio_url": "https://..."
  }
}
```

#### 1.3 Admin endpoint for filler generation

**File:** `backend/app/api/v1/tts_admin.py`

```python
@router.post("/filler/{business_id}")
async def generate_filler(
    business_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Generate and cache filler audio for a business."""
    db_service = DBService(db)
    business = await db_service.get_business(business_id)
    if not business:
        raise HTTPException(404, "Business not found")

    voice_config = get_voice_config(business.ai_config)
    results = await generate_filler_audio(business_id, voice_config)

    # Update business config with filler URL
    ai_config = business.ai_config or {}
    ai_config.setdefault("voice", {})
    ai_config["voice"]["filler_audio_url"] = results["thinking"].audio_url

    await db_service.update_business(business_id, {"ai_config": ai_config})

    return {"status": "ok", "filler_audio_url": results["thinking"].audio_url}
```

---

### Phase 2: Refactor Voice Flow

**Estimated effort:** 2-3 hours

#### 2.1 Modify `process_speech` to return filler immediately

**File:** `backend/app/api/v1/voice.py`

**Current approach (lines 411-441):**
```python
# Continue conversation
conversation["post_response_action"] = "gather"
tts_status = await _enqueue_tts_response(
    response,
    ai_response["text"],
    business.ai_config if business else {},
    business_id,
    call_sid,
    timeout_seconds=4.0,
)
# ... handle tts_status
```

**New approach:**
```python
# Store response for async TTS synthesis
conversation["pending_tts_text"] = ai_response["text"]
conversation["pending_tts_voice_config"] = voice_config
conversation["post_response_action"] = "gather"

# Start TTS synthesis in background
tts_provider = resolve_tts_provider(voice_config)
conversation["tts_task"] = asyncio.create_task(
    tts_provider.synthesize(ai_response["text"], voice_config)
)

# Immediately return filler + redirect
response = VoiceResponse()
filler_url = (business.ai_config or {}).get("voice", {}).get("filler_audio_url")
if filler_url:
    response.play(filler_url)
else:
    # Fallback: short pause then redirect
    response.pause(length=1)

response.redirect(f"/voice/tts-ready/{business_id}/{call_sid}")
return Response(content=str(response), media_type="application/xml")
```

#### 2.2 Add new endpoint: `/voice/tts-ready`

**File:** `backend/app/api/v1/voice.py`

```python
@router.post("/tts-ready/{business_id}/{call_sid}")
async def tts_ready(
    business_id: str,
    call_sid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Return TTS response after filler audio has played.
    Called via redirect from process_speech.
    """
    conversation = conversations.get(call_sid, {})
    if not conversation:
        response = VoiceResponse()
        response.say(
            "Sorry, I lost track of our conversation. Please call back!",
            voice='Polly.Nicole',
            language='en-AU'
        )
        return Response(content=str(response), media_type="application/xml")

    pending_text = conversation.get("pending_tts_text", "")
    tts_task = conversation.get("tts_task")

    response = VoiceResponse()
    tts_audio = None

    # Await background TTS task with generous timeout
    # (user is hearing filler, so we have more time)
    if tts_task:
        try:
            tts_audio = await asyncio.wait_for(tts_task, timeout=8.0)
        except asyncio.TimeoutError:
            print(f"⚠️ TTS timeout for call {call_sid}")
            tts_audio = None
        except Exception as e:
            print(f"❌ TTS error for call {call_sid}: {e}")
            tts_audio = None

    # Play TTS audio or fallback to native
    if tts_audio and tts_audio.audio_url:
        response.play(tts_audio.audio_url)
    else:
        response.say(pending_text, voice='Polly.Nicole', language='en-AU')

    # Continue conversation with Gather if needed
    if conversation.get("post_response_action") == "gather":
        gather = Gather(
            input='speech',
            action=f'/voice/process/{business_id}/{call_sid}',
            timeout=5,
            speech_timeout='auto',
            language='en-AU'
        )
        response.append(gather)
        response.say(
            "Are you still there? Call back anytime!",
            voice='Polly.Nicole',
            language='en-AU'
        )
    elif conversation.get("post_response_action") == "end":
        # Cleanup conversation
        if call_sid in conversations:
            del conversations[call_sid]

    # Clear pending state
    conversation.pop("pending_tts_text", None)
    conversation.pop("tts_task", None)

    return Response(content=str(response), media_type="application/xml")
```

#### 2.3 Update booking completion flow

Apply same pattern to booking confirmation responses (`voice.py:394-409`).

---

### Phase 3: Optimize Deepgram Provider

**Estimated effort:** 1-2 hours

#### 3.1 Add connection pooling

**File:** `backend/app/integrations/tts/providers/deepgram.py`

```python
# Module-level shared client
_http_client: httpx.AsyncClient | None = None

def _get_client() -> httpx.AsyncClient:
    """Get or create a shared HTTP client with connection pooling."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _http_client


class DeepgramTTSProvider:
    # ... existing code ...

    async def synthesize(self, text: str, voice: VoiceConfig) -> AudioResult:
        # Use shared client instead of creating new one
        client = _get_client()
        response = await client.post(
            "https://api.deepgram.com/v1/speak",
            # ... rest of request
        )
```

#### 3.2 Optimize cache lookup

Current flow does two operations:
1. Check if signed URL exists (round-trip)
2. If not, synthesize and upload

Optimize to single path:
```python
async def synthesize(self, text: str, voice: VoiceConfig) -> AudioResult:
    # ... hash computation ...

    # Try to get signed URL directly (will fail if doesn't exist)
    signed_url = self.storage.create_signed_url(audio_path)
    if signed_url:
        return AudioResult(audio_url=signed_url, cached=True, ...)

    # Cache miss - synthesize
    # ... synthesis code ...
```

---

### Phase 4: Metrics & Monitoring

**Estimated effort:** 1 hour

#### 4.1 Add latency tracking

```python
# In process_speech, track timing
timing = {
    "ai_start": time.time(),
    "ai_end": None,
    "filler_returned": None,
    "tts_complete": None,
}

# After AI response
timing["ai_end"] = time.time()

# Before returning filler
timing["filler_returned"] = time.time()

# Store in conversation for tts_ready to complete
conversation["timing"] = timing
```

#### 4.2 Log metrics in tts_ready

```python
timing = conversation.get("timing", {})
timing["tts_complete"] = time.time()

logger.info("voice.latency", extra={
    "call_sid": call_sid,
    "ai_latency_ms": int((timing["ai_end"] - timing["ai_start"]) * 1000),
    "time_to_filler_ms": int((timing["filler_returned"] - timing["ai_start"]) * 1000),
    "tts_latency_ms": int((timing["tts_complete"] - timing["ai_end"]) * 1000),
    "total_latency_ms": int((timing["tts_complete"] - timing["ai_start"]) * 1000),
    "tts_cached": tts_audio.cached if tts_audio else False,
})
```

---

## Files to Modify

| File | Phase | Changes |
|------|-------|---------|
| `app/integrations/tts/greeting.py` | 1 | Add `generate_filler_audio()` |
| `app/api/v1/tts_admin.py` | 1 | Add `/filler/{business_id}` endpoint |
| `app/api/v1/voice.py` | 2 | Refactor `process_speech`, add `tts_ready` |
| `app/integrations/tts/providers/deepgram.py` | 3 | Connection pooling, optimize cache |

---

## Rollout Strategy

### Step 1: Feature Flag
Add `use_proactive_filler` to business `ai_config`:
```json
{
  "voice": { ... },
  "use_proactive_filler": false
}
```

### Step 2: Test with Single Business
1. Enable flag for one test business
2. Generate filler audio via admin endpoint
3. Make test calls, monitor latency metrics
4. Verify fallback works if TTS fails

### Step 3: Gradual Rollout
1. Enable for 10% of businesses
2. Monitor error rates and latency
3. If stable, enable for all

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Filler feels unnatural | Use business's TTS voice for consistency |
| TTS still fails after filler | Existing `<Say>` fallback remains |
| Background task memory leak | Clean up tasks in conversation cleanup |
| Filler URL expires | Use long TTL or public URLs for filler clips |

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Time to first audio | 1.6 - 3.8s | <0.5s (filler) |
| Time to TTS response | 1.6 - 3.8s | <2.0s |
| TTS cache hit rate | Unknown | >20% |
| Fallback to `<Say>` rate | Unknown | <5% |

---

## Future Improvements (Post-MVP)

These are out of scope for this refactor but noted for future:

1. **Twilio Media Streams** - Full WebSocket-based streaming for <800ms latency
2. **Streaming STT** - Replace `<Gather>` with Deepgram Nova streaming
3. **Streaming TTS** - Play audio as tokens generate
4. **Speculative generation** - Start LLM before user finishes speaking
5. **Semantic caching** - Cache similar queries, not just exact matches

---

## Approval Checklist

- [ ] Plan reviewed and approved
- [ ] Filler audio text confirmed ("Let me check that for you.")
- [ ] Test business identified for rollout
- [ ] Monitoring/alerting requirements confirmed

---

*Last updated: January 20, 2026*
