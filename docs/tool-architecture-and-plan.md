# Tool Architecture and Plan

> **Goal:** Add tool capability to the streaming-first architecture so the LLM can fetch fresh, tenant-scoped data (bookings, policies, FAQs) from Supabase.
> **Scope (now):** DB tables only. Read-only tools. No restrictions beyond tenant scoping. Webhook code removal is assumed elsewhere.
> **Scope (later):** RAG, permission gating, write tools, richer policy enforcement.

---

## Core Idea

Introduce a **tool router** inside the backend that the streaming LLM can call during a live session. Tools are **typed, tenant-scoped, read-only** and return structured data from Supabase. The CallSession orchestrates tool calls, merges results into the LLM context, and resumes streaming TTS.

This plan uses a **single streaming model with mid-stream tool calls** (no separate intent step) to keep latency low while still allowing tools when needed.

---

## Architecture Overview

```
Twilio Media Streams
   ↕ (WebSocket)
Backend (CallSession)
   ↕
Tool Router  ────▶ Supabase (tenant tables)
   ↕
Streaming LLM (tool-calling)
   ↕
Streaming TTS
```

Key principles:
- **Streaming-safe:** Tool calls can pause token streaming, execute, then resume.
- **Tenant-scoped:** Every tool call requires business_id.
- **Strict schema:** Tool inputs/outputs are JSON-schema validated.
- **Read-only for now:** No mutations to DB.
- **Tool calls mid-stream:** Max 2 tool calls per user turn (MVP).

---

## Proposed Tool Set (Phase 1)

1. `get_latest_booking`
   - Input: `business_id`, `customer_phone` (or `call_sid`)
   - Output: most recent booking status + time + service

2. `get_booking_by_id`
   - Input: `business_id`, `booking_id`
   - Output: booking details

3. `get_business_services`
   - Input: `business_id`
   - Output: list of services from `businesses.services`

4. `get_working_hours`
   - Input: `business_id`
   - Output: business hours from `businesses.working_hours`

5. `get_policies`
   - Input: `business_id`, optional `topic`
   - Output: policy text/snippet

6. `get_faqs`
   - Input: `business_id`, optional `topic`
   - Output: FAQ entries

---

## Data Model (Supabase)

Current models in `backend/app/models`:

- `bookings` (id, business_id, call_id, customer_name, customer_phone, customer_email, service, booking_datetime, duration_minutes, status, confirmed_at, price, customer_notes, internal_notes, created_at, updated_at)
- `businesses` (id, name, industry, phone, email, twilio_number, ai_config, services, working_hours, created_at, updated_at)
- `calls` (id, business_id, call_sid, caller_phone, started_at, ended_at, duration_seconds, transcript, intent, outcome, sentiment_score, confidence_score, recording_url, created_at)

New tables to add (Phase 1/2):

- `policies` (id, business_id, topic, content, updated_at)
- `faqs` (id, business_id, question, answer, tags, updated_at)

Availability is not currently modeled. If needed, add later:

- `availability` (id, business_id, service, start_time, end_time, is_available)

---

## Tool Router Design

**File:** `backend/app/tools/tool_registry.py`

Responsibilities:
- Register tool definitions + JSON schemas
- Validate inputs/outputs
- Enforce tenant scoping (`business_id` required)
- Execute tool function
- Return structured payloads + metadata

Example structure:

```python
@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    handler: Callable[..., Awaitable[dict]]
```

---

## Streaming LLM Integration

**File:** `backend/app/services/streaming_ai_service.py`

Add a tool-aware streaming pipeline:
- LLM can emit tool calls mid-stream
- Backend executes tool calls and injects results into the model as tool messages
- Continue streaming tokens → TTS

Flow:
1. LLM emits tool call JSON
2. Backend pauses TTS streaming
3. Tool executes (Supabase query)
4. Tool result is inserted as a tool response
5. LLM continues with final answer

MVP limits:
- Max 2 tool calls per user turn
- 200-400ms timeout per tool, 1s total cap
- Primary booking lookup key: `customer_phone`
- Policy/FAQ tool calls must include a topic string

---

## CallSession Changes

**File:** `backend/app/services/call_session.py`

Add fields:
- `tool_context`: dict
- `tool_history`: list
- `tool_latency_ms`: list

Add logic:
- On tool call: execute via Tool Router
- Add tool results into streaming AI context
- Resume token streaming
- If tool fails: fallback to safe response

---

## Supabase Integration Strategy

**File:** `backend/app/integrations/db/supabase_client.py`

- Centralized Supabase client
- Shared query helpers per tool
- Read-only access
- Timeouts (<200ms per tool call)
- Query `businesses.services` and `businesses.working_hours` directly (no services table yet)

---

## Rollout Plan

### Phase 1 (Week 1)
- Implement Tool Router + schemas
- Add tool-enabled streaming AI service
- Implement 2 core tools: `get_latest_booking`, `get_policies`
- Log tool latency + errors

### Phase 2 (Week 2)
- Add `get_faqs`, `get_services`, `get_booking_by_id`
- Add caching layer (per call, TTL)
- Add safe fallback templates

### Phase 3 (Week 3)
- Add `get_availability`
- Add lightweight guardrails (basic validation)
- Start enabling on select businesses

---

## Precise Streaming Flow (MVP)

1. **Call setup**
   - Create `CallSession`
   - Load `Business` by `business_id`
   - Build tenant system prompt from `businesses` + `ai_config`

2. **STT streaming**
   - Deepgram streams partial + final transcripts
   - On final: send utterance to LLM stream

3. **LLM streaming with tools**
   - Model streams tokens and can emit `tool_call`
   - Backend pauses TTS while tool executes
   - Tool result injected as `tool_result`
   - Model resumes streaming response

4. **TTS streaming**
   - Tokens → TTS streaming → Twilio playback

5. **Post-response**
   - Append assistant response to history
   - Cache tool results in session for follow-ups

---

## Tool Call Protocol (JSON)

Tool call request (LLM → backend):

```json
{
  "type": "tool_call",
  "tool_name": "get_latest_booking",
  "arguments": {
    "business_id": "uuid",
    "customer_phone": "+61400111222"
  }
}
```

Tool call response (backend → LLM):

```json
{
  "type": "tool_result",
  "tool_name": "get_latest_booking",
  "result": {
    "booking_id": "uuid",
    "status": "confirmed",
    "service": "Haircut",
    "booking_datetime": "2026-01-24T10:30:00Z",
    "customer_name": "Sarah M"
  }
}
```

---

## System Prompt Template (Tenant-Scoped)

```
SYSTEM:
You are Echo, the AI receptionist for {business_name} ({industry}).
Tone: {tone}. Language: {language}. Keep responses short (1-2 sentences).
Services: {services_summary}
Working hours: {working_hours_summary}

If the caller asks about booking status, policies, FAQs, services, or hours,
use the appropriate tool. For policies/FAQs you must request a topic string.
Suggested policy/FAQ topics: cancellation, reschedule, late arrival, deposits,
refunds, pricing, hours, location, parking.

Always be professional, concise, and accurate. If a tool fails, apologize
and offer to take a message.
```

---

## Tool Usage Policy (Prompt Addendum)

```
TOOLS:
- Use tools only when you need fresh, tenant-specific data.
- Max 2 tool calls per user turn.
- If a tool fails or times out, reply with:
  "I'm having trouble pulling that up right now. Would you like me to take a message?"
- Policies/FAQs require a topic string.
- Suggested policy/FAQ topics: cancellation, reschedule, late arrival, deposits,
  refunds, pricing, hours, location, parking.
- Booking lookups must use customer_phone from the call.
```

---

## Admin Seeding (Examples)

Populate policies and FAQs via admin endpoints:

```bash
# Create a policy
curl -X POST "$API_BASE/tts_admin/policies/{business_id}" \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "cancellation",
    "content": "Cancellations within 24 hours incur a 50% fee."
  }'

# List policies (optional topic filter)
curl "$API_BASE/tts_admin/policies/{business_id}?topic=cancellation"

# Create an FAQ
curl -X POST "$API_BASE/tts_admin/faqs/{business_id}" \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "parking",
    "question": "Is there parking available?",
    "answer": "Yes, free street parking is available after 6pm.",
    "tags": ["parking", "location"]
  }'

# List FAQs (optional topic filter)
curl "$API_BASE/tts_admin/faqs/{business_id}?topic=parking"
```

Example responses:

```json
{
  "status": "ok",
  "policy": {
    "id": "a8b0f8f1-3a6b-4b3e-9e6c-2b6b8e6d4e01",
    "business_id": "1f1f1f1f-2a2b-3c3d-4e4f-5a5b5c5d5e5f",
    "topic": "cancellation",
    "content": "Cancellations within 24 hours incur a 50% fee.",
    "updated_at": "2026-01-22T10:05:12.123456"
  }
}
```

```json
{
  "status": "ok",
  "faqs": [
    {
      "id": "b2c3d4e5-6f70-4a3b-9c8d-1e2f3a4b5c6d",
      "business_id": "1f1f1f1f-2a2b-3c3d-4e4f-5a5b5c5d5e5f",
      "topic": "parking",
      "question": "Is there parking available?",
      "answer": "Yes, free street parking is available after 6pm.",
      "tags": ["parking", "location"],
      "updated_at": "2026-01-22T10:06:45.654321"
    }
  ]
}
```

---

## Observability

Log per tool:
- Tool name
- Latency
- Result size
- Failure reason

Suggested metric key:
- `tool.calls.count`
- `tool.calls.latency_ms`
- `tool.calls.errors`

---

## Risks + Mitigations

| Risk | Mitigation |
|------|------------|
| Tool latency impacts streaming | Enforce timeouts + cached fallback |
| Incorrect tenant data | Require `business_id` in all queries |
| Overfetching data | Limit columns; return summaries |
| Tool errors | Graceful LLM fallback responses |

---

## Future Additions (Post-MVP)

- RAG layer on policies/FAQs
- Tool permissioning by role
- Write-capable tools (e.g., create booking)
- Multi-tool chaining policies

---

*Last updated: January 22, 2026*
