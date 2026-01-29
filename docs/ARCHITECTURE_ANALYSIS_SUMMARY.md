# System Architecture Analysis & Calendar Integration Strategy

## Executive Summary

After careful analysis of the call flow and system architecture, we found that the system already has a **clean abstraction layer** for booking providers. This means calendar integration can be implemented with minimal changes to core systems.

**Recommendation**: Implement `GoogleCalendarProvider` that plugs into the existing provider interface.

---

## System Architecture Overview

### Current Data Flow
```
┌─────────────────────────────────────────────────────────────────┐
│                        INCOMING CALL                              │
│  voice/incoming/{business_id}/{call_sid}                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              CallSession (Long-lived WebSocket)                   │
│  • STT Input → LLM Streaming → TTS Output                        │
│  • Maintains conversation history                               │
│  • Collects: name, phone, service, datetime                     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
           ┌───────────────────────────────┐
           │  Booking Complete?            │
           │  (All data collected)         │
           └───────────────┬───────────────┘
                           │
                    ┌──────▼──────┐
                    │YES       NO │
                    │         LOOP│
                    │            │
        ┌───────────▼──────────┐ │
        │ check_availability() │ │
        │   (Provider API)     │ │
        └───────────┬──────────┘ │
                    │            │
            ┌───────▼────────┐   │
            │ Available?     │   │
            │YES       NO    │   │
            │           └────┼───┘
            │ (ask for alt)  │
        ┌───▼────────┐       │
        │create_     │       │
        │booking()   │       │
        └───┬────────┘       │
            │                │
        ┌───▼────────────────┘
        │
        ▼
┌──────────────────────────┐
│ after_booking()          │
│ (Post-processing hook)   │
└──────────────────────────┘
        │
        ▼
┌──────────────────────────┐
│ Send SMS Confirmation    │
│ End Call                 │
└──────────────────────────┘
```

### Provider Interface (Existing)

```python
class BookingProvider(Protocol):
    name: str
    
    async def check_availability(context: BookingContext) → AvailabilityResult
    async def create_booking(context: BookingContext) → BookingIntent
    async def after_booking(context: BookingContext, booking_id: str) → None
```

**Current Implementation**: `NativeBookingProvider` (always returns available=True)

---

## Calendar Integration Architecture

### Proposed Design

```
┌─────────────────────────────────────────────────────────────────┐
│         GoogleCalendarProvider (implements BookingProvider)      │
│                                                                   │
│  ✓ check_availability()                                          │
│    └─> GoogleCalendarClient.get_free_busy()                     │
│        └─> Google Calendar API (freebusy endpoint)              │
│                                                                   │
│  ✓ create_booking()                                              │
│    └─> Return BookingIntent(status="confirmed")                 │
│                                                                   │
│  ✓ after_booking()                                               │
│    └─> GoogleCalendarClient.create_event()                      │
│        └─> Google Calendar API (events endpoint)                │
└─────────────────────────────────────────────────────────────────┘
```

### File Structure
```
backend/app/integrations/
├── google_calendar/           (EXISTING)
│   ├── __init__.py
│   ├── oauth.py              (✅ DONE)
│   ├── models.py             (✅ DONE)
│   ├── client.py             ← NEW (API wrapper)
│   └── provider.py           ← NEW (BookingProvider impl)
│
├── providers/
│   ├── base.py               (✅ EXISTING - Protocol definition)
│   ├── native.py             (✅ EXISTING - Native provider)
│   ├── google_calendar.py    ← NEW (Registry wrapper)
│   └── registry.py           (UPDATE - Register provider)
```

---

## Call Flow with Google Calendar Integrated

```
BEFORE: (Current)
┌──────────────────┐
│ Booking Complete │
└────────┬─────────┘
         │
         ▼
┌──────────────────────────────┐
│ NativeBookingProvider        │
│ check_availability() → TRUE  │
└────────┬─────────────────────┘
         │
         ▼
┌──────────────────────────────┐
│ Create Booking (DB)          │
│ Send SMS                     │
└──────────────────────────────┘

AFTER: (With Google Calendar)
┌──────────────────┐
│ Booking Complete │
└────────┬─────────┘
         │
         ▼
┌──────────────────────────────────────┐
│ GoogleCalendarProvider               │
│                                      │
│ check_availability()                 │
│  ├─ Load encrypted token from DB    │
│  ├─ Refresh if expired              │
│  ├─ Call get_free_busy(time)        │
│  └─ Return TRUE/FALSE               │
└────────┬─────────────────────────────┘
         │
    ┌────▼────┐
    │ Available? │
    └────┬────┘
    YES  │  NO
        │  └──→ "That time is booked"
        │       Ask for alt time
        ▼
┌────────────────────────────────────────┐
│ Create Booking (DB)                    │
│ + after_booking() callback             │
│   ├─ GoogleCalendarProvider.          │
│   │  after_booking()                  │
│   │  ├─ Create event in Google Cal   │
│   │  └─ Store event_id in DB        │
│   └─                                  │
│ Send SMS                              │
└────────────────────────────────────────┘
```

---

## Key Design Benefits

### ✅ Minimal Core Changes
- **No changes to**: `voice.py`, `call_session.py`, or booking creation logic
- **Only update**: `registry.py` (1 file, ~5 lines)
- **New files**: `client.py`, `provider.py`, wrapper in providers/

### ✅ Follows Existing Patterns
- Reuses proven `BookingProvider` interface
- Integrates with existing `after_booking()` hook
- Uses same error handling strategy

### ✅ Graceful Degradation
If calendar is:
- **Not connected** → Return `available=True` (native behavior)
- **API down** → Return `available=True` (never fail booking)
- **Token expired** → Auto-refresh transparently
- **Rate limited** → Log and fallback to available

### ✅ Future Flexibility
Can support:
- Multiple calendar providers (Google, Outlook, Calendly)
- Chain multiple providers (check all before confirming)
- Different availability rules per service
- Configurable booking duration per service

---

## Implementation Detail: Token & Token Management

### Problem
Google OAuth returns short-lived access tokens (1 hour) and long-lived refresh tokens.

### Solution
```
┌─────────────────────────────────────────┐
│ Business Model (Database)               │
├─────────────────────────────────────────┤
│ google_calendar_id: "primary"           │
│ google_refresh_token: [ENCRYPTED]       │ ← Stored securely
│ google_token_expires_at: datetime       │ ← When access token expires
└─────────────────────────────────────────┘
                    │
                    │ (on each API call)
                    ▼
┌────────────────────────────────────────┐
│ GoogleCalendarClient                    │
│ _get_valid_access_token()              │
│  1. Check if token expired              │
│  2. If yes, decrypt refresh token      │
│  3. Call Google to get new access token│
│  4. Update expiration in DB            │
│  5. Return access_token (temp, uncached)
└────────────────────────────────────────┘
```

**Why this approach:**
- Refresh tokens never expire (unless revoked)
- Access tokens auto-refreshed on demand
- Transparent to caller
- Zero background jobs needed

---

## Configuration

### Business Settings (ai_config)

To enable Google Calendar for a business, set:

```json
{
  "integrations": {
    "provider": "google_calendar",
    "providers": {
      "google_calendar": {
        "enabled": true,
        "check_availability": true,
        "create_events": true,
        "default_duration_minutes": 60
      }
    }
  }
}
```

### Provider Resolution
```python
# In voice.py or call_session.py, somewhere:
provider_config = get_provider_config(business.ai_config)
provider = resolve_provider(provider_config, business)

# Now provider is either:
# - NativeBookingProvider (if not configured)
# - GoogleCalendarProvider (if configured)
```

---

## Error Scenarios & Handling

### Scenario 1: Calendar Not Connected
```
business.google_refresh_token = None
→ check_availability() returns AvailabilityResult(available=True)
→ Booking proceeds as normal
✓ Zero impact
```

### Scenario 2: Availability Check Fails
```
try:
    conflicts = await client.get_free_busy(...)
except Exception as e:
    logger.error(f"Calendar check failed: {e}")
    return AvailabilityResult(available=True)  # Graceful fallback
✓ Booking still succeeds
```

### Scenario 3: Event Creation Fails
```
booking = create_booking(...)  # ✓ Succeeds
try:
    await provider.after_booking(...)  # Create calendar event
except Exception as e:
    logger.warning(f"Calendar event creation failed: {e}")
    # Don't re-raise, booking already created
✓ Booking preserved, calendar sync skipped
```

### Scenario 4: Token Expired
```
access_token = None
expires_at < now
→ Automatically decrypt refresh token & refresh
→ Get new access token
→ Use for API call
→ Update expires_at
✓ Transparent, no user impact
```

---

## Testing Strategy

### Unit Tests (GoogleCalendarClient)
```python
test_get_free_busy_no_conflicts()      # Returns empty list
test_get_free_busy_with_conflicts()    # Returns busy times
test_create_event_success()            # Returns event_id
test_token_refresh_on_expiry()         # Auto-refreshes
test_handles_network_errors()          # Doesn't crash
```

### Integration Tests (GoogleCalendarProvider)
```python
test_check_availability_available()    # Returns True
test_check_availability_busy()         # Returns False
test_after_booking_creates_event()     # Event created
test_gracefully_handles_missing_token() # Returns available=True
```

### End-to-End Tests
```python
test_full_call_flow_creates_calendar_event()
test_double_booking_prevention()
test_booking_succeeds_if_calendar_down()
```

### Manual Test Plan
1. Connect Google Calendar in Settings
2. Create event at 2pm in Google Calendar
3. Call in, try to book 2pm
   - ✗ Should be rejected: "That time is booked"
4. Try to book 3pm
   - ✓ Should be accepted
   - ✓ Check Google Calendar: event created
5. Call in again, try to book 3pm
   - ✗ Should be rejected: already booked by our system
6. Disconnect calendar in Settings
7. Call in, try to book 2pm (which was busy)
   - ✓ Should be accepted: calendar no longer checked

---

## Rollout & Risk Mitigation

### Low Risk Because:
1. ✅ Plugs into existing provider interface
2. ✅ Graceful degradation on all errors
3. ✅ Can test with single business first
4. ✅ Easy to roll back (switch provider in config)
5. ✅ No database migrations needed initially (event_id optional)

### Rollout Phases:
1. **Dev/Staging** (Week 1-2): Implement + unit tests
2. **Single Pilot Business** (Week 3): Manual testing with real calls
3. **Rollout to Others** (Week 4+): Enable in their ai_config when ready
4. **Monitor**: Watch logs for calendar API errors

### Kill Switch:
If issues arise, simply change business ai_config:
```json
{
  "integrations": {
    "provider": "native"  // ← Switches back immediately
  }
}
```

---

## Success Metrics

✓ **Availability Accuracy**: Double-bookings prevented
✓ **Latency**: Availability check < 500ms (with token refresh)
✓ **Reliability**: 99%+ calendar operations succeed (with fallback)
✓ **Event Creation**: 100% of confirmed bookings create calendar events
✓ **User Experience**: Seamless integration, no new UI needed

---

## Next Steps

1. **Read the detailed architecture** in `CALENDAR_INTEGRATION_ARCHITECTURE.md`
2. **Implement Phase 1**: GoogleCalendarClient
3. **Test thoroughly**: Unit + integration tests
4. **Implement Phase 2**: GoogleCalendarProvider + registry
5. **Manual testing**: With real calls and real Google Calendar

---

## Questions to Discuss

- ✓ Architecture approach (provider pattern) - **APPROVED**
- Should we cache access tokens in memory? (Current: refresh on each API call)
- Should default duration be configurable per service?
- Should we notify user if calendar event creation fails?
- How often should we refresh tokens proactively vs on-demand?

