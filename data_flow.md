# Streaming Voice Call Data Flow

This document describes the end-to-end data flow for a **streaming voice call** from the moment a caller dials the business number until the call ends.

The focus is on **events** and the **core component (Class.Method)** that handles each step.

---

## High-Level Flow

1. **Caller dials Twilio number** → Twilio hits FastAPI **webhook**.
2. Webhook creates a **call record** and returns TwiML that connects a **Twilio Media Stream** to our WebSocket.
3. **WebSocket** connection is established and a **CallSession** is created.
4. CallSession initializes **STT** and **TTS** and plays the greeting.
5. Caller speaks → audio is streamed to **STT**, transcripts are generated.
6. When an utterance ends, the **ConversationEngine** processes it via LLM + tools.
7. AI response is streamed back via **TTS** to the caller.
8. Optionally, a **booking** is created and **SMS** is sent.
9. Call ends and resources are cleaned up.

---

## Flow Diagram (Events → Components)

```mermaid
flowchart TD
  A[User dials Twilio business number] --> B[HTTP POST /stream/incoming/{business_id}\nmedia_stream.incoming_call_stream]
  B --> C[Twilio connects WebSocket\nGET /stream/ws/{business_id}/{call_sid}\nmedia_stream.media_stream_websocket]
  C --> D[Create CallSession instance\nCallSession.__init__]
  D --> E[Initialize session (load business, STT, TTS, greeting)\nCallSession.initialize]
  E --> F[Caller audio chunks (Twilio 'media' events)\nCallSession.handle_twilio_message]
  F --> G[Decode + forward audio to STT\nCallSession._handle_incoming_audio]
  G --> H[STT final transcript events\nCallSession._on_transcript]
  H --> I[UtteranceEnd from STT\nCallSession._on_utterance_end]
  I --> J[Debounced processing + LLM/tools\nCallSession._debounced_process_utterance\n→ CallSession._process_with_llm\n→ ConversationEngine.process_utterance]
  J --> K[AI response spoken via streaming TTS\nCallSession.speak / speak_streaming\n→ CallSession._on_tts_audio]
  K --> L[Audio played to caller by Twilio]
  J --> M[Optional booking creation + SMS\nbooking_logic.maybe_create_booking\nDBService.create_booking\ntwilio_client.send_sms]
  K --> N[Call end decision\nCallSession._should_end_call\nCallSession._end_call]
  M --> N
  N --> O[Cleanup & metrics\nCallSession.cleanup]
```

---

## Step-by-Step Events and Components

### 1. Incoming Call (Webhook)

- **Event**: Caller dials the Twilio number.
- **Component**: `media_stream.incoming_call_stream` (FastAPI route `/stream/incoming/{business_id}`).
- **What it does**:
  - Reads `CallSid`, `From`, `To` from Twilio POST.
  - Looks up the business via `DBService.get_business_by_phone` / `get_business`.
  - Creates a `call` record via `DBService.create_call`.
  - Builds TwiML that:
    - Plays a cached greeting or a fallback TTS greeting.
    - Connects a `<Stream>` to our WebSocket at `/stream/ws/{business_id}/{call_sid}`.

### 2. WebSocket Connection and Session Creation

- **Event**: Twilio opens a WebSocket to `/stream/ws/{business_id}/{call_sid}`.
- **Component**: `media_stream.media_stream_websocket`.
- **What it does**:
  - Accepts the WebSocket connection.
  - Constructs a new `CallSession` instance.
  - Enters a loop reading JSON messages from Twilio.

### 3. Stream Start and Session Initialization

- **Event**: Twilio sends a `start` event on the WebSocket.
- **Components**:
  - `CallSession.handle_twilio_message` (receives the `start` event).
  - `media_stream.media_stream_websocket` (special-cases `start` to set context).
  - `CallSession.initialize`.
- **What it does**:
  - Extracts custom parameters (business name, caller phone, call_id).
  - Registers the session via `register_session(session)`.
  - Calls `CallSession.initialize`, which:
    - Loads business context from DB via `_load_business_context`.
    - Connects to **Deepgram STT** via `_connect_stt`.
    - Connects to **Deepgram TTS** via `_connect_tts`.
    - Appends an assistant greeting to `conversation_history` via `_play_greeting`.

### 4. Audio Streaming from Caller

- **Event**: Twilio sends `media` events with base64 μ-law audio chunks.
- **Components**:
  - `CallSession.handle_twilio_message` (branches on `event == "media"`).
  - `CallSession._handle_incoming_audio`.
- **What it does**:
  - Decodes the base64 audio.
  - Forwards audio bytes to Deepgram STT via `stt_connection.send_audio`.
  - Tracks first audio timestamps in `CallMetrics`.

### 5. Transcription and Utterance Detection

- **Events**:
  - STT partial and final transcripts.
  - STT `UtteranceEnd` when silence is detected.
- **Components**:
  - `CallSession._on_transcript`.
  - `CallSession._on_utterance_end`.
- **What they do**:
  - `_on_transcript`:
    - Logs partial vs final transcripts.
    - Accumulates final transcripts into `current_transcript`.
    - Records `first_transcript_at` in `CallMetrics`.
  - `_on_utterance_end`:
    - Marks `is_user_speaking = False`.
    - Moves the accumulated `current_transcript` into `conversation_history` as a `{"role": "user"}` entry.
    - Schedules debounced processing via `_debounced_process_utterance`.

### 6. LLM + Tooling + Business Logic

- **Event**: User utterance is ready to be processed.
- **Components**:
  - `CallSession._debounced_process_utterance`.
  - `CallSession._process_with_llm`.
  - `ConversationEngine.process_utterance`.
  - (Booking path) `booking_logic.maybe_create_booking`.
- **What they do**:
  - `_debounced_process_utterance`:
    - Waits a short grace period (debounce) to avoid duplicate processing.
    - Ensures only one LLM call at a time using `_processing_lock`.
    - Calls `_process_with_llm(utterance)`.
  - `_process_with_llm`:
    - Creates a `ConversationEngine` with `ConversationEngineConfig(session=self)`.
    - Delegates to `ConversationEngine.process_utterance`, which:
      - Calls the LLM.
      - May call tools via `CallSession._execute_tool`.
      - May trigger booking creation via `booking_logic.maybe_create_booking`.

### 7. Speaking Back to the Caller (TTS → Twilio)

- **Event**: AI response text is ready.
- **Components**:
  - `CallSession.speak` or `CallSession.speak_streaming`.
  - `CallSession._on_tts_audio`.
  - `CallSession._on_tts_complete`.
- **What they do**:
  - `speak` / `speak_streaming`:
    - Append the assistant message to `conversation_history`.
    - Send text chunks to Deepgram TTS and flush.
  - `_on_tts_audio`:
    - Marks `is_ai_speaking = True`.
    - Records `first_response_audio_at` for metrics.
    - Sends audio bytes to Twilio via `send_audio` (WebSocket `media` event back to Twilio).
  - `_on_tts_complete`:
    - Marks `is_ai_speaking = False`.
    - Increments `total_ai_responses`.
    - Optionally sends a `mark` event if the call is scheduled to end.

### 8. Optional Booking Creation and SMS

- **Event**: Conversation indicates a booking is complete.
- **Components**:
-  - `BookingWorkflow.handle_turn`.
-  - `booking_logic.maybe_create_booking`.
-  - `DBService.create_booking`.
-  - `twilio_client.send_sms`.
- **What they do**:
-  - BookingWorkflow inspects the latest AI/user turns and decides when to attempt booking creation.
-  - `booking_logic.maybe_create_booking` evaluates whether sufficient data exists and, if so, creates a booking via `DBService.create_booking`.
-  - A confirmation SMS is sent to the customer using `twilio_client.send_sms`.
-  - Call outcome/intent is updated in the database.

### 9. Deciding to End the Call

- **Event**: User or AI indicates the conversation is finished (e.g., farewell after booking).
- **Components**:
  - `CallSession._should_end_call`.
  - `CallSession._end_call`.
  - `CallSession._end_call_timeout` (fail-safe).
- **What they do**:
  - `_should_end_call`:
    - Detects farewell phrases in user or AI text.
    - Considers whether a booking has been created.
  - `_end_call`:
    - Updates the call record via `_update_call_record(outcome="completed", ended=True)`.
    - Uses `twilio_client.client.calls(self.call_sid).update(status="completed")` to hang up.
  - `_end_call_timeout`:
    - Ensures the call is ended even if Twilio marks don’t arrive as expected.

### 10. Cleanup and Metrics

- **Event**: WebSocket disconnects or call is ended.
- **Components**:
  - `media_stream.media_stream_websocket` (finally block).
  - `CallSession.cleanup`.
  - `unregister_session`.
- **What they do**:
  - `cleanup`:
    - Cancels background tasks.
    - Closes STT and TTS connections.
    - Logs call metrics via `CallMetrics.log_summary`.
  - `unregister_session`:
    - Removes the `CallSession` from the in-memory session registry.

---

This flow should give you a concise map from **real-world events** (caller actions, Twilio messages, STT/LLM outputs) to the **core Python components** that handle each step.

---

## Notes on Recent Improvements

- **Intent-based services**: Business services can now be seeded directly from the plumbing intent mapping sheet via `backend/app/services/intent_profiles.py` and the helper script `backend/scripts/update_business_services_from_intents.py`.
- **Safer call end heuristics**: `CallSession._should_end_call` has been updated so that polite phrases like "thank you" or "thanks" do not, on their own, terminate a call; only explicit farewells (e.g. "bye", "that's all") combined with context will schedule call end, and any new user speech cancels a pending end.
