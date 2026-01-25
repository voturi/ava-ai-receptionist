# Detailed Changes Reference

## File: `backend/app/services/call_session.py`

### Change 1: Add Concurrency Control Fields to CallSession Dataclass

**Location**: Lines 140-143  
**Type**: Field Addition

```python
# Concurrency control (FIX #1: Prevent concurrent LLM processing)
_processing_lock: Optional[asyncio.Lock] = None
_utterance_debounce_task: Optional[asyncio.Task] = None
_last_utterance_time: float = 0.0
```

**Purpose**: Add instance variables to track:
- `_processing_lock`: Lock to ensure sequential LLM processing
- `_utterance_debounce_task`: Current debounce task for cancellation
- `_last_utterance_time`: (Placeholder for future use)

---

### Change 2: Initialize Lock in __post_init__

**Location**: Lines 147-149  
**Type**: Constructor Modification

```python
def __post_init__(self):
    self.metrics = CallMetrics(call_sid=self.call_sid)
    self.metrics.started_at = datetime.utcnow()
    # Initialize lock (can't use field(default_factory) for Lock)
    self._processing_lock = asyncio.Lock()
```

**Purpose**: Create asyncio.Lock instance for this session. Must be done in `__post_init__` because Lock cannot be created in `field(default_factory)`.

---

### Change 3: Replace _on_utterance_end() Method

**Location**: Lines 1090-1129  
**Type**: Method Replacement

**Before**:
```python
async def _on_utterance_end(self) -> None:
    self.is_user_speaking = False
    if self.current_transcript and self.current_transcript.strip():
        full_utterance = self.current_transcript.strip()
        self.current_transcript = ""
        print(f"🛑 Utterance complete: {full_utterance}")
        self.metrics.total_user_utterances += 1
        self.conversation_history.append({
            "role": "user",
            "content": full_utterance,
        })
        # ❌ PROBLEM: Immediately creates task - no debouncing
        asyncio.create_task(self._process_with_llm(full_utterance))
    else:
        print(f"🛑 Utterance end (no transcript)")
```

**After**:
```python
async def _on_utterance_end(self) -> None:
    """
    Handle end of user utterance (VAD detected silence).

    This is the RIGHT time to process - user has actually stopped speaking.
    Uses debouncing to prevent multiple rapid UtteranceEnd events from
    triggering multiple concurrent LLM calls (FIX #2).
    """
    self.is_user_speaking = False

    if self.current_transcript and self.current_transcript.strip():
        full_utterance = self.current_transcript.strip()
        self.current_transcript = ""  # Clear for next utterance

        print(f"🛑 Utterance detected: {full_utterance}")

        self.metrics.total_user_utterances += 1

        # Add to conversation history
        self.conversation_history.append({
            "role": "user",
            "content": full_utterance,
        })

        # ✅ FIX: Debounce: Cancel pending debounce task and create a new one
        # This ensures we only process once even if UtteranceEnd fires multiple times
        if self._utterance_debounce_task and not self._utterance_debounce_task.done():
            self._utterance_debounce_task.cancel()
            try:
                await self._utterance_debounce_task
            except asyncio.CancelledError:
                pass

        # Schedule processing with 500ms grace period
        # If another UtteranceEnd arrives before this, it cancels this task
        self._utterance_debounce_task = asyncio.create_task(
            self._debounced_process_utterance(full_utterance)
        )
    else:
        print(f"🛑 Utterance end (no transcript)")
```

**Key Changes**:
1. Changed log from "complete" to "detected" (indicates not immediately processing)
2. Added debounce logic: cancel previous task if exists
3. Schedule new debounced task instead of immediate `_process_with_llm()`

---

### Change 4: Add New _debounced_process_utterance() Method

**Location**: Lines 1131-1154  
**Type**: New Method Addition

```python
async def _debounced_process_utterance(self, utterance: str) -> None:
    """
    Process utterance after grace period, ensuring only one LLM call at a time.
    
    Args:
        utterance: The user's spoken text
    """
    try:
        # Grace period: wait 500ms to see if user speaks again
        # This prevents processing incomplete thoughts
        await asyncio.sleep(0.5)

        # Acquire lock to ensure only one LLM processing happens at a time (FIX #1)
        async with self._processing_lock:
            print(f"🤖 Processing utterance (after debounce grace period): {utterance[:50]}...")
            await self._process_with_llm(utterance)

    except asyncio.CancelledError:
        print(f"🛑 Utterance debounce cancelled (user spoke again)")
        pass
    except Exception as e:
        print(f"❌ Error in debounced utterance processing: {e}")
        import traceback
        traceback.print_exc()
```

**Purpose**:
- Wait 500ms before processing (allows user to continue speaking)
- Acquire lock before LLM processing (prevents concurrent calls)
- Handle cancellation gracefully (if user speaks again)
- Log errors for debugging

---

### Change 5: Increase STT Endpointing Threshold

**Location**: Line 323  
**Type**: Parameter Modification

**Before**:
```python
config=STTConfig(
    model="nova-2",
    language="en-AU",
    sample_rate=8000,
    encoding="mulaw",
    interim_results=True,
    utterance_end_ms=2000,  # Wait 2s of silence before UtteranceEnd (allows thinking pauses)
    endpointing=1000,  # ❌ 1s silence for final transcript chunks
),
```

**After**:
```python
config=STTConfig(
    model="nova-2",
    language="en-AU",
    sample_rate=8000,
    encoding="mulaw",
    interim_results=True,
    utterance_end_ms=2000,  # Wait 2s of silence before UtteranceEnd (allows thinking pauses)
    endpointing=2500,  # ✅ FIX #3: Increased from 1000ms to 2500ms to allow natural speech pauses
),
```

**Impact**: Changes how long Deepgram waits before finalizing a transcript chunk
- 1000ms: Too aggressive, cuts off "May I know what," 
- 2500ms: Allows natural thinking pauses, more complete sentences

---

## Summary of Changes

| # | Type | Location | Change | Purpose |
|---|------|----------|--------|---------|
| 1 | Fields | Lines 140-143 | Add concurrency control fields | Enable debouncing & locking |
| 2 | Init | Line 149 | Initialize asyncio.Lock() | Create lock for session |
| 3 | Method | Lines 1090-1129 | Rewrite _on_utterance_end() | Add debouncer logic |
| 4 | New Method | Lines 1131-1154 | Add _debounced_process_utterance() | Grace period + lock acquisition |
| 5 | Parameter | Line 323 | Increase endpointing 1000→2500ms | Prevent cutting off users |

---

## Code Flow Diagram

### Before (Broken)
```
User speaks → Deepgram STT → UtteranceEnd event (possibly multiple)
                                    ↓
                        _on_utterance_end() fires
                                    ↓
                    asyncio.create_task(_process_with_llm)
                                    ↓
                    [RACE CONDITION - multiple concurrent LLM calls]
                                    ↓
                    Multiple TTS responses overlap
```

### After (Fixed)
```
User speaks → Deepgram STT → UtteranceEnd event (possibly multiple)
                                    ↓
                        _on_utterance_end() fires
                                    ↓
                    Cancel previous debounce task (if exists)
                                    ↓
                    Schedule new debounce task (500ms delay)
                                    ↓
                    [If another UtteranceEnd arrives → restart loop]
                                    ↓
                    After 500ms grace period → acquire lock
                                    ↓
                    _process_with_llm() runs (protected by lock)
                                    ↓
                    Only ONE LLM response
```

---

## Testing Points

### Unit Test: Debouncer
```python
# Simulate rapid UtteranceEnd events
session._on_utterance_end()  # Event 1
session._on_utterance_end()  # Event 2 (should cancel Event 1)
session._on_utterance_end()  # Event 3 (should cancel Event 2)

# After 500ms grace period, only one _process_with_llm call should occur
assert mock_llm_calls.count == 1
```

### Integration Test: Natural Speech Pauses
```
User: "Can I..." (pause 1.5s) "...schedule an appointment?"
Expected: System waits for complete sentence
Verify: Transcript includes full sentence
```

### Integration Test: Rapid Successive Utterances
```
User: "Hi"
[AI responds]
User: "When are you open?"
[AI responds]
User: "Can you help?"
[AI responds]
Expected: Three separate natural responses
Verify: No overlapping audio, coherent conversation
```

---

## Import Verification

All required imports are already present in the file:
- `asyncio` ✅ (line 14)
- `Optional` ✅ (line 21)
- `asyncio.Task` ✅ (available from asyncio import)

No new imports needed.

---

## Type Hints Verification

All type hints are correct:
- `_processing_lock: Optional[asyncio.Lock]` ✅ Valid
- `_utterance_debounce_task: Optional[asyncio.Task]` ✅ Valid
- `_last_utterance_time: float = 0.0` ✅ Valid

---

## Backward Compatibility

✅ All changes are backward compatible:
- No changes to public API
- No changes to method signatures
- No changes to database schema
- No changes to configuration format
- Existing code paths still work

---

## Performance Impact

**Expected**: Minimal to None
- Lock only held during LLM processing (already async)
- Debouncer adds 500ms latency (acceptable in conversation context)
- No additional database queries
- No additional network calls

**Memory**: Slight increase
- One Lock instance per session (~100 bytes)
- One Task reference (~50 bytes)
- One float for timestamp (~8 bytes)
- Total: ~158 bytes per active session

---

## Rollback Procedure

If needed to rollback:

```bash
# Option 1: Git revert
git revert <commit-hash>

# Option 2: Manual revert
# 1. Remove lines 140-143 (concurrency control fields)
# 2. Remove line 149 (lock initialization)
# 3. Replace lines 1090-1129 with old _on_utterance_end
# 4. Delete lines 1131-1154 (_debounced_process_utterance method)
# 5. Change line 323: endpointing=2500 → endpointing=1000
```

No data cleanup needed (only code changes).
