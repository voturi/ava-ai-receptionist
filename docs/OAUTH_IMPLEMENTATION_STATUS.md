# Google Calendar OAuth Implementation - Status & Next Steps

## ✅ Completed: OAuth Flow (End-to-End)

The complete OAuth 2.0 authentication flow is now fully implemented and tested.

### What Works
- **Frontend Settings Page**: Users can click "Connect" to initiate OAuth
- **OAuth Start Endpoint** (`POST /api/v1/auth/google-calendar/start`):
  - Verifies business exists
  - Generates Google OAuth authorization URL
  - Returns URL to frontend
- **OAuth Callback Handler** (`GET /api/v1/auth/google-calendar/callback`):
  - Receives authorization code from Google
  - Exchanges code for access & refresh tokens
  - Encrypts refresh token with Fernet
  - Saves encrypted token to database
  - Returns success response
- **Frontend Callback Page**: 
  - Displays loading state while processing
  - Shows success message and redirects to dashboard
  - Handles errors gracefully
- **Disconnect Endpoint** (`POST /api/v1/auth/google-calendar/disconnect`):
  - Clears stored credentials
  - Allows users to revoke access

### Technical Implementation
- Token encryption using `cryptography.Fernet`
- Async SQLAlchemy database operations
- FastAPI with dependency injection for database sessions
- Proper error handling and logging throughout
- Secure state parameter validation

### Commits on `google-calendar-integration` branch
```
9d488ab Remove React Router dependency from callback page
b57d179 Fix OAuth endpoints to use correct AsyncSession imports
5c0a9ab Add comprehensive Google Calendar OAuth setup guide
88c693d Implement Google Calendar OAuth flow
40a8844 Add calendar integration fields to Business model
fedf699 Add Settings page with calendar integration UI
```

---

## 🎯 Next: Calendar Client & Integration

With OAuth complete, the next phase is implementing actual calendar operations.

### Phase 2: Google Calendar Client

**Goal**: Create a client to interact with Google Calendar API

**What to build**:
```
backend/app/integrations/google_calendar/
├── client.py  (NEW)
│   ├── GoogleCalendarClient class
│   ├── get_calendars()
│   ├── check_availability(date, time)
│   ├── create_event(title, time, duration)
│   ├── update_event(event_id, ...)
│   └── delete_event(event_id)
├── models.py  (EXISTS)
├── oauth.py   (EXISTS)
└── __init__.py
```

**Key features**:
1. Token refresh logic (when access token expires)
2. Error handling for API failures
3. Rate limiting awareness
4. Timezone handling (use `google_calendar_timezone` from Business model)

**Example flow**:
```python
client = GoogleCalendarClient(business)  # Loads encrypted token from DB
client.check_availability("2026-01-27", "14:00-15:00")  # Returns: available/booked
client.create_event(
    title="Hair Cut - John Doe",
    start_time="2026-01-27T14:00:00",
    duration_minutes=60
)
```

### Phase 3: Booking Service Integration

**Goal**: Sync bookings with Google Calendar

**What to modify**:
1. `booking_service.py` - When booking is confirmed:
   - Check calendar availability first
   - Create calendar event if available
   - Handle failures gracefully
2. Add background job for token refresh

**Example logic**:
```python
async def create_booking(booking_request):
    # 1. Check calendar availability
    is_available = await calendar_client.check_availability(...)
    if not is_available:
        raise BookingUnavailable()
    
    # 2. Create booking in DB
    booking = await create_booking_in_db(...)
    
    # 3. Create calendar event
    try:
        await calendar_client.create_event(...)
    except Exception:
        # Log but don't fail - booking still created
        logger.warning(f"Failed to create calendar event for booking {booking.id}")
    
    return booking
```

### Phase 4: Calendly Integration (Similar)

- Create `calendly/oauth.py` with CalendlyOAuth class
- Create `calendly/client.py` with CalendlyClient class
- Reuse same booking integration pattern

---

## 📋 Implementation Checklist

### OAuth Phase (✅ DONE)
- [x] Database schema with calendar fields
- [x] Settings UI with Connect/Disconnect buttons
- [x] OAuth flow (start → Google → callback)
- [x] Token encryption and storage
- [x] Error handling and user feedback
- [x] Setup documentation

### Calendar Client Phase (⏭️ NEXT)
- [ ] GoogleCalendarClient class
- [ ] Token refresh logic
- [ ] check_availability() method
- [ ] create_event() method
- [ ] update_event() and delete_event() methods
- [ ] Unit tests for client
- [ ] Integration tests with real API

### Booking Integration Phase
- [ ] Modify booking service to check availability
- [ ] Create calendar events on booking confirmation
- [ ] Update events when bookings change
- [ ] Delete events when bookings cancel
- [ ] Background token refresh job

### Calendly Phase
- [ ] CalendlyOAuth class
- [ ] CalendlyClient class
- [ ] Same booking integration
- [ ] Testing

---

## 🔧 Current State

**What's stored in database** (after successful OAuth):
```
Business.google_calendar_id = "primary"
Business.google_refresh_token = "[encrypted token]"
Business.google_token_expires_at = datetime(...)
Business.google_calendar_timezone = "Australia/Sydney"  # (not yet set by frontend)
Business.auto_sync_bookings = True  # (toggle in settings)
```

**What's NOT yet implemented**:
- Reading the stored token and using it
- Refreshing expired tokens
- Making actual Google Calendar API calls
- Syncing bookings to calendar

---

## 🚀 Quick Start for Next Phase

1. **Create the calendar client**:
   ```bash
   touch backend/app/integrations/google_calendar/client.py
   ```

2. **Implement GoogleCalendarClient**:
   - Load encrypted token from Business model
   - Decrypt using GoogleCalendarOAuth.decrypt_token()
   - Use token to make API calls
   - Handle token refresh

3. **Test with a simple endpoint**:
   ```python
   @router.get("/api/v1/calendar/availability")
   async def check_availability(
       business_id: str,
       date: str,
       start_time: str,
       db: AsyncSession = Depends(get_db),
   ):
       business = await get_business(db, business_id)
       client = GoogleCalendarClient(business)
       available = await client.check_availability(date, start_time)
       return {"available": available}
   ```

4. **Add integration test** to verify it works with real Google Calendar

---

## 📚 References

- Google Calendar API: https://developers.google.com/calendar/api/guides
- OAuth 2.0 Refresh Token: https://developers.google.com/identity/protocols/oauth2#refreshing-an-access-token
- aiohttp: https://docs.aiohttp.org/
- SQLAlchemy async: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
