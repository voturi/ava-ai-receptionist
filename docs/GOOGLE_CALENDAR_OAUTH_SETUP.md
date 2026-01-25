# Google Calendar OAuth Setup Guide

This guide walks through setting up Google Calendar OAuth for the Digital Receptionist system.

## Overview

The OAuth flow enables users to authorize the system to access their Google Calendar without storing passwords. The system stores an encrypted refresh token that can be used to get new access tokens as needed.

## Architecture

```
Frontend (Settings page)
    ↓
[User clicks "Connect" button]
    ↓
POST /api/v1/auth/google-calendar/start (backend returns auth URL)
    ↓
Frontend redirects to Google OAuth consent screen
    ↓
User grants permission
    ↓
Google redirects to: /auth/google-calendar/callback?code=...&state=...
    ↓
GET /api/v1/auth/google-calendar/callback (backend exchanges code for tokens)
    ↓
Backend encrypts refresh token and saves to Business model
    ↓
Frontend redirected to dashboard
```

## Setup Steps

### 1. Create Google OAuth Application

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project or select existing one
3. Enable the **Google Calendar API**:
   - Search for "Google Calendar API"
   - Click "Enable"
4. Create OAuth 2.0 credentials:
   - Go to **Credentials** → **Create Credentials** → **OAuth client ID**
   - Application type: **Web application**
   - Add authorized redirect URIs:
     - **Development**: `http://localhost:5173/auth/google-calendar/callback`
     - **Production**: `https://yourdomain.com/auth/google-calendar/callback`
   - Copy **Client ID** and **Client Secret**

### 2. Configure Environment Variables

#### Backend (.env)
```bash
# Google Calendar OAuth
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:5173/auth/google-calendar/callback

# Generate encryption key:
# python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY=your-encryption-key
```

#### Frontend (.env)
```bash
# Should already be configured for local development
VITE_API_URL=http://localhost:8000
```

### 3. Install Dependencies

Backend dependencies are already in `requirements.txt`:
- `cryptography==41.0.7` - Token encryption
- `aiohttp==3.9.1` - Async HTTP for Google token exchange

Install if not already done:
```bash
cd backend
pip install -r requirements.txt
```

### 4. Database Setup

The Google Calendar fields were added to the `Business` model in a previous migration:
- `google_calendar_id` - Google Calendar identifier
- `google_refresh_token` - Encrypted refresh token
- `google_token_expires_at` - Token expiration timestamp
- `google_calendar_timezone` - Calendar timezone for scheduling

If not already applied, run:
```bash
cd backend
alembic upgrade head
```

## Testing the OAuth Flow

### Manual Testing

1. **Start backend**:
   ```bash
   cd backend
   python -m uvicorn app.main:app --reload
   ```

2. **Start frontend**:
   ```bash
   cd frontend
   npm run dev
   ```

3. **Navigate to Settings**:
   - Go to http://localhost:5173
   - Click "Settings" button
   - Click "Connect" for Google Calendar

4. **Authorize**:
   - You'll be redirected to Google's consent screen
   - Grant access to Calendar
   - You'll be redirected back to the callback page
   - Should see success message and redirect to dashboard

5. **Verify in Database**:
   ```bash
   sqlite3 dev.db
   SELECT google_calendar_id, google_token_expires_at FROM business WHERE id='your-business-id';
   ```

### Troubleshooting

#### "Failed to initiate OAuth flow"
- Ensure `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set
- Check that Google Calendar API is enabled in Cloud Console

#### "Missing authorization code or state"
- Ensure `GOOGLE_REDIRECT_URI` matches exactly in:
  - Google Cloud Console OAuth settings
  - Backend `.env` file
  - Frontend hardcoded URL

#### "Failed to get refresh token"
- Check that you're using an **online access type** in the authorization request
- Ensure the OAuth app has Calendar scopes enabled

#### Encryption errors
- Generate a new `ENCRYPTION_KEY` and update `.env`
- Note: Old encrypted tokens won't decrypt with new key - users must reconnect

## API Endpoints

### Start OAuth Flow
```bash
POST /api/v1/auth/google-calendar/start
Content-Type: application/json

{
  "business_id": "adf0c65d-02ca-4279-a741-8e7f7bb297ad"
}

Response:
{
  "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?..."
}
```

### OAuth Callback (Google redirect)
```bash
GET /api/v1/auth/google-calendar/callback?code=...&state=...

Response:
{
  "success": true,
  "message": "Google Calendar connected successfully"
}
```

### Disconnect Calendar
```bash
POST /api/v1/auth/google-calendar/disconnect
Content-Type: application/json

{
  "business_id": "adf0c65d-02ca-4279-a741-8e7f7bb297ad"
}

Response:
{
  "success": true,
  "message": "Google Calendar disconnected successfully"
}
```

## Security Considerations

1. **Token Storage**: Refresh tokens are encrypted using Fernet (symmetric encryption) before storage
2. **Encryption Key**: Must be kept secret and generated using `Fernet.generate_key()`
3. **HTTPS**: Always use HTTPS in production (not http://)
4. **Scopes**: Only requesting necessary Calendar scopes:
   - `calendar` - Read/write access to calendars
   - `calendar.events` - Read/write access to events

## Next Steps

After OAuth is working:

1. **Create Calendar Client** - Implement methods to:
   - List calendars
   - Check availability (free/busy)
   - Create events
   - Update/delete events

2. **Integrate with Bookings** - Modify booking flow to:
   - Check calendar availability before confirming bookings
   - Create calendar events for confirmed bookings
   - Update events when bookings change

3. **Add Calendly Support** - Similar flow for Calendly API

4. **Sync Management** - Add background job to:
   - Handle token refresh when expired
   - Sync calendar availability periodically
   - Handle sync errors and retry logic

## References

- [Google Calendar API Docs](https://developers.google.com/calendar/api)
- [OAuth 2.0 Authorization Code Flow](https://developers.google.com/identity/protocols/oauth2)
- [Python Cryptography Library](https://cryptography.io/en/latest/)
