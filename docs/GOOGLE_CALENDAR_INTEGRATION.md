# Google Calendar Integration Architecture

**Phase**: MVP (Weeks 1-8) → 70% Clean  
**Priority**: Speed to working integration  
**Status**: Design Phase

---

## 1. Problem Statement

### Current State
- Bookings are created in our database
- Business owners need to manually sync bookings to their calendar
- No real-time availability checking
- Double-booking risk

### Goal
- Integrate with Google Calendar API
- Create events automatically when bookings confirmed
- Check availability before booking
- Sync business calendar → our availability data

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      AI Receptionist                         │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Voice Call Flow                                             │
│  ├─ STT (Deepgram) → Transcript                            │
│  ├─ LLM → Booking Intent + Details                         │
│  └─ BOOKING CREATION POINT ←────────────────┐              │
│                                              │              │
│                                              ▼              │
│                              ┌──────────────────────────┐   │
│                              │  Booking Service         │   │
│                              │  ├─ Create booking       │   │
│                              │  ├─ Check availability   │   │
│                              │  └─ Send confirmations   │   │
│                              └──────────────────────────┘   │
│                                      │                       │
│                                      ▼                       │
│                          ┌─────────────────────────┐         │
│                          │ Google Calendar Client  │         │
│                          │ ├─ Check availability   │         │
│                          │ ├─ Create events        │         │
│                          │ ├─ Update events        │         │
│                          │ └─ Delete events        │         │
│                          └─────────────────────────┘         │
│                                      │                       │
└──────────────────────────────────────┼───────────────────────┘
                                       │
                                       ▼
                        ┌──────────────────────────┐
                        │  Google Calendar API     │
                        │  (External Service)      │
                        └──────────────────────────┘
```

---

## 3. Core Components (MVP - "Clean Enough")

### 3.1 Google Calendar Client
**File**: `backend/app/integrations/google_calendar/client.py`

```python
class GoogleCalendarClient:
    """
    Wrapper around Google Calendar API.
    MVP approach: Simple, direct API calls. 
    Will refactor to service layer if we add more calendar features.
    """
    
    def __init__(self, credentials: Credentials):
        self.service = build("calendar", "v3", credentials=credentials)
    
    # CRITICAL OPERATIONS (90% clean)
    async def create_event(self, event: CalendarEvent) -> str:
        """Create booking event in Google Calendar."""
        # With error handling, logging, type hints
    
    async def check_availability(
        self, 
        calendar_id: str, 
        start: datetime, 
        end: datetime
    ) -> bool:
        """Check if time slot is free in business calendar."""
        # With error handling, edge cases
    
    # SUPPORTING OPERATIONS (70% clean)
    async def update_event(self, event_id: str, event: CalendarEvent) -> None:
        """Update existing calendar event."""
        # Basic validation OK
    
    async def delete_event(self, event_id: str) -> None:
        """Delete calendar event when booking cancelled."""
        # Simple delete OK
```

---

### 3.2 Calendar Event Model
**File**: `backend/app/models/calendar.py`

```python
@dataclass
class CalendarEvent:
    """
    Represents a booking event for Google Calendar.
    
    MVP approach: Simple dataclass. No ORM needed for external calendar.
    """
    title: str                    # "Haircut - Jane Smith"
    description: str              # Booking details, phone, etc
    start_time: datetime          # Booking datetime
    end_time: datetime            # Start + service duration
    customer_email: Optional[str] # To send invitations
    customer_phone: str           # Stored in description
    service: str                  # What was booked
    business_id: str              # Which business
    booking_id: str               # Link back to our DB
```

---

### 3.3 Booking Service Integration
**File**: `backend/app/services/booking_service.py` (existing, modified)

```python
class BookingService:
    """
    Core booking logic. Now integrates with Google Calendar.
    """
    
    def __init__(
        self, 
        db_service: DBService,
        calendar_client: GoogleCalendarClient
    ):
        self.db = db_service
        self.calendar = calendar_client
    
    async def create_booking(
        self,
        business_id: str,
        customer_info: CustomerInfo,
        service: str,
        requested_datetime: datetime
    ) -> BookingResult:
        """
        MVP flow:
        1. Check availability in Google Calendar
        2. Create booking in our DB
        3. Create event in Google Calendar
        4. Send confirmation
        """
        
        try:
            # Step 1: Check Google Calendar
            is_available = await self.calendar.check_availability(
                calendar_id=business_id,
                start=requested_datetime,
                end=requested_datetime + timedelta(hours=1)
            )
            
            if not is_available:
                return BookingResult(
                    success=False,
                    reason="Time slot not available"
                )
            
            # Step 2: Create in our database
            booking = await self.db.create_booking({
                "business_id": business_id,
                "customer_name": customer_info.name,
                "customer_phone": customer_info.phone,
                "service": service,
                "booking_datetime": requested_datetime,
                "status": "confirmed"
            })
            
            # Step 3: Create in Google Calendar
            calendar_event = CalendarEvent(
                title=f"{service} - {customer_info.name}",
                description=f"Phone: {customer_info.phone}",
                start_time=requested_datetime,
                end_time=requested_datetime + timedelta(hours=1),
                customer_phone=customer_info.phone,
                service=service,
                business_id=business_id,
                booking_id=str(booking.id)
            )
            
            event_id = await self.calendar.create_event(calendar_event)
            
            # Step 4: Store calendar event ID for future updates
            await self.db.update_booking(booking.id, {
                "calendar_event_id": event_id
            })
            
            return BookingResult(success=True, booking=booking)
            
        except CalendarError as e:
            logger.error(f"Calendar API failed: {e}", extra={
                "business_id": business_id,
                "requested_datetime": requested_datetime
            })
            # Fallback: Create booking without calendar sync
            # Customer gets SMS, but manual calendar sync needed
            return BookingResult(
                success=True,
                booking=booking,
                warning="Could not sync to calendar - manual sync needed"
            )
```

---

## 4. Authentication Flow (OAuth 2.0)

### 4.1 Setup Flow (Business Owner)
```
1. Business owner clicks "Connect Google Calendar" button
2. Redirected to Google OAuth consent screen
3. Grants permission to read/write calendar
4. Google redirects back with authorization code
5. Backend exchanges code for refresh token
6. Store refresh token in database (encrypted)
7. Test connection by creating test event
```

### 4.2 Credentials Storage
**File**: `backend/app/models/business.py` (modify existing)

```python
class Business(Base):
    # ... existing fields ...
    
    # Google Calendar integration
    google_calendar_id: Optional[str] = None  # "business@company.com"
    google_refresh_token: Optional[str] = None  # Encrypted
    google_token_expires_at: Optional[datetime] = None
    
    # Which calendar to use for availability checking
    google_calendar_timezone: str = "Australia/Sydney"
```

---

## 5. Implementation Plan (MVP)

### Phase 1: Foundation (Week 1-2)
- [ ] Create Google Cloud project + OAuth credentials
- [ ] Implement `GoogleCalendarClient` basic methods
- [ ] Add `CalendarEvent` model
- [ ] Create OAuth login endpoint

### Phase 2: Integration (Week 3-4)
- [ ] Modify `BookingService` to check availability
- [ ] Add calendar event creation on booking confirmation
- [ ] Add event deletion on booking cancellation
- [ ] Store calendar event IDs in database

### Phase 3: Testing & Polish (Week 5-6)
- [ ] Manual testing with real Google Calendar
- [ ] Error handling for network issues
- [ ] Graceful degradation if calendar unavailable
- [ ] Business owner UI to configure calendar

### Phase 4: Refinement (Week 7-8)
- [ ] Add timezone handling
- [ ] Handle recurring business hours
- [ ] SMS notification with calendar confirmation
- [ ] Documentation for business setup

---

## 6. Error Handling Strategy

### Critical Operations (90% Clean)
```python
async def check_availability(...) -> bool:
    try:
        # Query Google Calendar
        events = self.service.events().list(
            calendarId=calendar_id,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True
        ).execute()
        
        return len(events.get("items", [])) == 0
        
    except HttpError as e:
        logger.error(f"Google Calendar API error: {e}", extra={
            "status_code": e.resp.status,
            "calendar_id": calendar_id
        })
        # Fallback: Assume available (error on side of caution)
        return True
        
    except TimeoutError as e:
        logger.warning(f"Calendar check timeout: {e}")
        # Fallback: Don't block booking
        return True
```

### Fallback Strategy
- If Google Calendar is down: Still create booking, send SMS, manual sync later
- If authorization expires: Prompt business owner to reconnect
- If event creation fails: Log error, notify support, manual followup

---

## 7. Data Model Changes

### Database Updates
```python
# In calls table
calendar_event_id: str  # Link to Google Calendar event

# In bookings table  
calendar_event_id: str  # Link to Google Calendar event

# In businesses table
google_calendar_id: str
google_refresh_token: str (encrypted)
google_token_expires_at: datetime
google_calendar_timezone: str
```

---

## 8. API Endpoints (Phase 4)

```
POST /api/v1/auth/google-calendar/start
  ↓ Redirects to Google OAuth

GET /api/v1/auth/google-calendar/callback?code=...
  ↓ Exchanges code for token, saves to DB

POST /api/v1/settings/{business_id}/calendar/disconnect
  ↓ Removes Google Calendar connection

GET /api/v1/settings/{business_id}/calendar/status
  ↓ Returns connection status
```

---

## 9. "Clean Enough" Decisions

### What We're NOT Doing in MVP
❌ Advanced calendar features (recurring events, resource management, etc)  
❌ Multiple calendar support  
❌ Custom event templates  
❌ Automatic rescheduling  
❌ Calendar sharing with customers  

### Why
- Extra complexity with unclear customer value
- Google Calendar API is powerful but we only need 5% of it
- Better to add features after customers ask (not before)

### When We Refactor (Post-PMF)
- Extract `CalendarService` when we add email invitations + notifications
- Build calendar settings UI after 20+ businesses request customization
- Add advanced features when competitors do (not before)

---

## 10. Testing Strategy (MVP)

### Manual Testing (70% clean = good enough)
```
1. Create Google Cloud test project
2. Get OAuth credentials
3. Test in development:
   - Connect calendar
   - Create booking → Check Google Calendar event appears
   - Cancel booking → Check event deleted
   - Network failure → Verify fallback works
```

### No Unit Tests Yet
- Calendar client code will change as we learn integration
- Wait until Week 8 when code stabilizes
- Then add tests for happy path + error cases

---

## 11. Dependencies

### New Python Packages
```
google-auth==2.x          # Google OAuth
google-auth-oauthlib==1.x # OAuth flow
google-auth-httplib2==0.2 # HTTP client
google-api-python-client  # Calendar API
cryptography==42.x        # Encrypt tokens
```

### Why These
- Official Google libraries
- Already used in production by 1000s of services
- Better than trying to roll our own OAuth

---

## 12. Rollout Plan

### Week 1: Internal Testing
- Praveen tests with personal Google Calendar
- Verify availability checking works
- Check events appear correctly

### Week 2-3: Beta Customers
- Opt-in feature for willing customers
- Monitor for issues
- Collect feedback

### Week 4+: General Release
- Add to onboarding flow
- Feature highlight in emails
- Documentation

---

## 13. Known Limitations

1. **Timezone Handling**: Assume business timezone = Australia/Sydney
   - TODO: Allow customization after PMF

2. **Availability Checking**: Only checks exact 1-hour slots
   - TODO: Support variable service durations post-PMF

3. **Event Updates**: No partial updates (delete + recreate)
   - TODO: Implement proper updates if business edits frequently

4. **Business Hours**: Doesn't respect working hours yet
   - TODO: Add hour/day rules after Week 8

---

## 14. Success Metrics

### MVP Success = 
- ✅ Zero customer complaints about double-bookings
- ✅ 80% of bookings synced to calendar automatically
- ✅ <1% failure rate (graceful fallback works)
- ✅ <100ms availability check latency

### Post-PMF Improvements =
- ✅ 95%+ sync success rate
- ✅ Timezone customization available
- ✅ Business hours respected
- ✅ Event updates work correctly

---

## 15. Migration Path (After We Have Customers)

### Current State (Week 8)
- Google Calendar integration working
- Manual calendar syncing needed for past bookings

### Week 12+
- Batch import existing bookings to calendar
- Business owner triggers sync from dashboard
- Email notification when sync complete

---

## References

- [Google Calendar API Docs](https://developers.google.com/calendar)
- [OAuth 2.0 for Desktop Apps](https://developers.google.com/identity/protocols/oauth2)
- [Engineering Philosophy](./engineering-philosophy.md#phase-1-mvp-weeks-1-8--70-clean)

---

**Branch**: `google-calendar-integration`  
**Status**: Design Complete - Ready for Implementation  
**Next**: Create Google Cloud project + implement GoogleCalendarClient
