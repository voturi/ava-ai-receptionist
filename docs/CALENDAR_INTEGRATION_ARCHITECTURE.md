# Google Calendar Integration: Architecture & Call Flow Design

## Current System Architecture

### Call Flow (Current)
```
1. Incoming Call → voice/incoming/{business_id}/{call_sid}
2. AI Stream → LLM + TTS (via call_session.py)
3. Collect: name, phone, service, datetime
4. Check Availability → provider.check_availability(context)
5. Create Booking → provider.create_booking(context)
6. Send SMS confirmation
7. End Call
```

### Provider Interface (Existing)
```python
class BookingProvider(Protocol):
    async def check_availability(context: BookingContext) → AvailabilityResult
    async def create_booking(context: BookingContext) → BookingIntent
    async def after_booking(context: BookingContext, booking_id: str) → None
```

The system has a **clean abstraction layer** - currently using `NativeBookingProvider` that always returns `available=True`.

---

## ✅ RECOMMENDED: GoogleCalendarProvider Pattern

### Why This Approach

Implement Google Calendar as a new provider that plugs into the existing provider interface:

**Benefits:**
- ✅ Plugs into existing provider abstraction
- ✅ No changes needed to call_session.py or voice.py  
- ✅ Follows "clean enough, fast enough" philosophy
- ✅ Easy to swap between Google Calendar and native availability
- ✅ Can chain multiple providers in future

### File Structure

```
backend/app/integrations/
├── google_calendar/
│   ├── __init__.py
│   ├── oauth.py        (✅ exists)
│   ├── models.py       (✅ exists)
│   ├── client.py       (NEW - Google API wrapper)
│   └── provider.py     (NEW - BookingProvider implementation)
└── providers/
    ├── base.py          (✅ exists)
    ├── native.py        (✅ exists)
    ├── google_calendar.py  (NEW - thin wrapper)
    └── registry.py      (UPDATE - register provider)
```

---

## Design: GoogleCalendarProvider

### Core Implementation

**app/integrations/google_calendar/provider.py:**
```python
class GoogleCalendarProvider:
    name = "google_calendar"
    
    def __init__(self, business: Business):
        self.business = business
        self.client = GoogleCalendarClient(business)
    
    async def check_availability(self, context: BookingContext) → AvailabilityResult:
        """
        1. Load encrypted token from Business model
        2. Refresh token if expired
        3. Query Google Calendar API for conflicts
        4. Return AvailabilityResult
        """
        if not self.business.google_refresh_token:
            # Calendar not connected, fall back to always available
            return AvailabilityResult(available=True)
        
        try:
            # Check if requested time conflicts with calendar
            requested_dt = context.requested_datetime
            if not requested_dt:
                return AvailabilityResult(available=True)
            
            # Query calendar for conflicts (60 min default duration)
            conflicts = await self.client.get_free_busy(
                start=requested_dt,
                duration_minutes=60
            )
            
            if conflicts:
                return AvailabilityResult(
                    available=False,
                    reason=f"Sorry, that time is already booked. Would another time work?"
                )
            
            return AvailabilityResult(available=True)
            
        except Exception as e:
            logger.error(f"Calendar availability check failed: {e}")
            # Graceful fallback: assume available
            return AvailabilityResult(available=True)
    
    async def create_booking(self, context: BookingContext) → BookingIntent:
        """
        1. Return status=confirmed
        2. Calendar event creation happens in after_booking()
        """
        return BookingIntent(status="confirmed")
    
    async def after_booking(self, context: BookingContext, booking_id: str) → None:
        """
        Called AFTER booking is created in DB.
        Creates corresponding Google Calendar event.
        """
        if not self.business.google_refresh_token:
            return  # Calendar not connected, skip
        
        try:
            event_id = await self.client.create_event(
                title=f"{context.service} - {context.customer.name}",
                start_time=context.requested_datetime,
                duration_minutes=60,
                description=f"Customer: {context.customer.phone}"
            )
            
            # Store event ID for future updates/cancellations
            await self._update_booking_with_event_id(booking_id, event_id)
            
            logger.info(f"Created calendar event {event_id} for booking {booking_id}")
            
        except Exception as e:
            # Don't fail the booking if calendar creation fails
            logger.warning(f"Failed to create calendar event for booking {booking_id}: {e}")
```

**app/integrations/providers/google_calendar.py (wrapper):**
```python
from app.integrations.google_calendar.provider import GoogleCalendarProvider as _GoogleCalendarProvider
from app.models import Business

class GoogleCalendarProvider:
    """Wrapper that matches BookingProvider protocol"""
    name = "google_calendar"
    
    def __init__(self, business: Business):
        self._provider = _GoogleCalendarProvider(business)
    
    async def check_availability(self, context: BookingContext) → AvailabilityResult:
        return await self._provider.check_availability(context)
    
    async def create_booking(self, context: BookingContext) → BookingIntent:
        return await self._provider.create_booking(context)
    
    async def after_booking(self, context: BookingContext, booking_id: str) → None:
        return await self._provider.after_booking(context, booking_id)
```

---

## Google Calendar Client

**app/integrations/google_calendar/client.py:**
```python
class GoogleCalendarClient:
    """Handles all Google Calendar API interactions"""
    
    def __init__(self, business: Business):
        self.business = business
        self.oauth = google_oauth  # singleton from oauth.py
    
    async def get_free_busy(
        self, 
        start: datetime, 
        duration_minutes: int = 60
    ) → List[Dict]:
        """
        Query Google Calendar for busy times
        
        Returns list of conflicting events (empty if available)
        """
        access_token = await self._get_valid_access_token()
        
        end = start + timedelta(minutes=duration_minutes)
        
        # Call Google Calendar freebusy API
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://www.googleapis.com/calendar/v3/freeBusy",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "timeMin": start.isoformat() + "Z",
                    "timeMax": end.isoformat() + "Z",
                    "items": [{"id": self.business.google_calendar_id}]
                }
            ) as resp:
                data = await resp.json()
                
                calendar_id = self.business.google_calendar_id
                busy_times = data.get("calendars", {}).get(calendar_id, {}).get("busy", [])
                
                return busy_times  # Empty list = available
    
    async def create_event(
        self,
        title: str,
        start_time: datetime,
        duration_minutes: int,
        description: str = ""
    ) → str:
        """
        Create event in Google Calendar
        
        Returns: event_id
        """
        access_token = await self._get_valid_access_token()
        
        end_time = start_time + timedelta(minutes=duration_minutes)
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://www.googleapis.com/calendar/v3/calendars/{self.business.google_calendar_id}/events",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "summary": title,
                    "description": description,
                    "start": {
                        "dateTime": start_time.isoformat(),
                        "timeZone": self.business.google_calendar_timezone or "UTC"
                    },
                    "end": {
                        "dateTime": end_time.isoformat(),
                        "timeZone": self.business.google_calendar_timezone or "UTC"
                    }
                }
            ) as resp:
                data = await resp.json()
                return data["id"]
    
    async def _get_valid_access_token(self) → str:
        """
        Get valid access token, refreshing if expired
        
        Returns: access_token
        """
        # Check if token is expired
        now = datetime.utcnow()
        expires_at = self.business.google_token_expires_at
        
        if expires_at and expires_at > now + timedelta(minutes=5):
            # Token still valid (with 5 min buffer)
            # In real implementation, we'd cache access_token
            # For now, we always refresh since we don't store access_token
            pass
        
        # Decrypt refresh token
        encrypted_token = self.business.google_refresh_token
        refresh_token = self.oauth.decrypt_token(encrypted_token)
        
        # Get new access token
        access_token, expires_in = await self.oauth.refresh_access_token(refresh_token)
        
        # Update expiration time in database
        new_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        self.business.google_token_expires_at = new_expires_at
        # Note: In real implementation, commit this to DB
        
        return access_token
```

---

## Call Flow with Google Calendar

```
1. Customer calls → voice/incoming/{business_id}
2. AI collects: name, service, datetime
3. Booking complete? → check_availability()
   │
   ├─ Resolve provider from ai_config: "google_calendar"
   │  └─ GoogleCalendarProvider.check_availability(context)
   │     └─ GoogleCalendarClient.get_free_busy(start, duration=60)
   │        ├─ Refresh access token if needed
   │        └─ Query Google Calendar freebusy API
   │           ├─ Conflicts found? → Return AvailabilityResult(available=False)
   │           └─ No conflicts → Return AvailabilityResult(available=True)
   │
4. Available? → create_booking()
   ├─ Create booking in local DB (existing flow)
   └─ after_booking() callback
      └─ GoogleCalendarProvider.after_booking(context, booking_id)
         └─ GoogleCalendarClient.create_event(...)
            └─ Create event in Google Calendar
               └─ Store event_id in Booking model
5. Success → Send SMS + Confirmation
6. End Call
```

---

## Configuration

### Business Configuration (ai_config)
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

### Provider Resolution (registry.py)
```python
_PROVIDERS: dict[str, Type[BookingProvider]] = {
    "native": NativeBookingProvider,
    "google_calendar": GoogleCalendarProvider,
}

def resolve_provider(config: dict, business: Business) → BookingProvider:
    provider_name = config.get("provider", "native")
    ProviderClass = _PROVIDERS.get(provider_name, NativeBookingProvider)
    return ProviderClass(business)  # Pass business for calendar access
```

---

## Error Handling Strategy

### Graceful Degradation

```python
async def check_availability(self, context) → AvailabilityResult:
    try:
        conflicts = await self.client.get_free_busy(...)
        return AvailabilityResult(available=not conflicts)
    except Exception as e:
        logger.error(f"Calendar check failed: {e}")
        # IMPORTANT: Don't fail booking due to calendar errors
        return AvailabilityResult(available=True)  # Assume available
```

### Failure Scenarios
- **Token expired** → Auto-refresh before API call
- **API rate limit** → Return unavailable, suggest alternate times
- **Network error** → Log and fallback to available=True
- **Invalid calendar ID** → Log error, notify admin

---

## Database Changes

### Booking Model Addition
```python
# app/models.py - Add to Booking model
external_event_id = Column(String, nullable=True)  # Google Calendar event ID
```

Migration:
```bash
alembic revision --autogenerate -m "Add external_event_id to bookings"
alembic upgrade head
```

---

## Implementation Phases

### Phase 1: Client & Token Management (NEXT)
- [x] OAuth flow complete
- [ ] Create `google_calendar/client.py`
  - [ ] get_free_busy() method
  - [ ] create_event() method
  - [ ] _get_valid_access_token() with auto-refresh
- [ ] Add `external_event_id` to Booking model
- [ ] Unit tests for client

### Phase 2: Provider Integration
- [ ] Create `google_calendar/provider.py`
- [ ] Create `providers/google_calendar.py` wrapper
- [ ] Update `registry.py` to register provider
- [ ] Integration tests for provider

### Phase 3: Configuration & Testing
- [ ] Update Business ai_config to select provider
- [ ] End-to-end manual testing
- [ ] Double-booking prevention test
- [ ] Calendar event creation verification

### Phase 4: Enhancements
- [ ] Update events when bookings change
- [ ] Delete events when bookings cancel
- [ ] Support multiple calendars
- [ ] Background token refresh job

---

## Testing Strategy

### Unit Tests
```python
test_google_calendar_client.py
├─ test_get_free_busy_no_conflicts()
├─ test_get_free_busy_with_conflicts()
├─ test_create_event_success()
├─ test_token_refresh_on_expiry()
└─ test_handles_api_errors_gracefully()

test_google_calendar_provider.py
├─ test_check_availability_available()
├─ test_check_availability_busy()
├─ test_create_booking_returns_confirmed()
└─ test_after_booking_creates_event()
```

### Integration Tests
```python
test_e2e_google_calendar.py
├─ test_full_booking_flow_with_calendar()
├─ test_double_booking_prevention()
└─ test_booking_creates_without_calendar_connected()
```

### Manual Test Plan
1. Set business provider to "google_calendar" in ai_config
2. Connect Google Calendar via Settings page
3. Manually create event in Google Calendar at 2pm
4. Call in, try to book 2pm → Should get "not available"
5. Try to book 3pm → Should succeed and create calendar event
6. Check Google Calendar → Event should exist

---

## Rollout Plan

1. **Week 1**: Implement GoogleCalendarClient (get_free_busy, create_event)
2. **Week 2**: Implement GoogleCalendarProvider + registry integration
3. **Week 3**: Testing + bug fixes + database migration
4. **Week 4**: Deploy to staging, manual testing with real calls
5. **Week 5**: Enable for 1-2 pilot businesses, monitor logs
6. **Week 6**: General availability

---

## Success Metrics

- ✅ Bookings trigger automatic Google Calendar event creation
- ✅ Double-booking prevention (conflicts detected before booking)
- ✅ Availability check latency < 500ms (including token refresh)
- ✅ 99% success rate for calendar operations (with graceful fallback)
- ✅ Zero failed bookings due to calendar errors

---

## Key Decisions

✅ **Use provider pattern** - aligns with existing architecture
✅ **Graceful degradation** - never fail bookings due to calendar
✅ **Auto token refresh** - transparent to caller
✅ **Store event IDs** - enable future updates/cancellations
✅ **Async throughout** - non-blocking for low latency
