"""Google Calendar OAuth endpoints"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models import Business
from app.integrations.google_calendar.oauth import google_oauth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/google-calendar", tags=["google-calendar"])


class GoogleCalendarStartRequest(BaseModel):
    business_id: str


class GoogleCalendarStartResponse(BaseModel):
    authorization_url: str


class GoogleCalendarAuthSuccess(BaseModel):
    success: bool
    message: str


@router.post("/start", response_model=GoogleCalendarStartResponse)
async def start_oauth_flow(
    request: GoogleCalendarStartRequest,
    db: AsyncSession = Depends(get_db),
) -> GoogleCalendarStartResponse:
    """
    Initiate Google Calendar OAuth flow
    
    Returns authorization URL for user to visit
    """
    # Verify business exists
    result = await db.execute(select(Business).where(Business.id == request.business_id))
    business = result.scalar_one_or_none()
    
    if not business:
        raise HTTPException(status_code=403, detail="Business not found")
    
    try:
        auth_url = google_oauth.get_authorization_url(business_id=request.business_id)
        logger.info(f"Generated OAuth URL for business {request.business_id}")
        return GoogleCalendarStartResponse(authorization_url=auth_url)
    except Exception as e:
        logger.error(f"Failed to generate OAuth URL: {e}")
        raise HTTPException(status_code=500, detail="Failed to initiate OAuth flow")


@router.get("/callback")
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(...),  # business_id passed as state
    db: AsyncSession = Depends(get_db),
) -> GoogleCalendarAuthSuccess:
    """
    Google OAuth callback endpoint
    
    Exchanges authorization code for tokens and saves to database
    """
    business_id = state
    
    # Verify business exists
    result = await db.execute(select(Business).where(Business.id == business_id))
    business = result.scalar_one_or_none()
    if not business:
        logger.error(f"Business {business_id} not found during OAuth callback")
        raise HTTPException(status_code=404, detail="Business not found")
    
    try:
        # Exchange code for tokens
        access_token, refresh_token, expires_in = await google_oauth.exchange_code_for_tokens(code)
        
        if not refresh_token:
            logger.error(f"No refresh token received for business {business_id}")
            raise HTTPException(status_code=500, detail="Failed to get refresh token")
        
        # Encrypt and store tokens
        encrypted_refresh_token = google_oauth.encrypt_token(refresh_token)
        
        # Calculate expiration time
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        
        # Update business with calendar credentials
        business.google_calendar_id = "primary"  # Use default calendar
        business.google_refresh_token = encrypted_refresh_token
        business.google_token_expires_at = expires_at
        
        db.add(business)
        await db.commit()
        
        logger.info(f"Successfully saved Google Calendar credentials for business {business_id}")
        
        return GoogleCalendarAuthSuccess(
            success=True,
            message="Google Calendar connected successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"OAuth callback error for business {business_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to process OAuth callback")


class DisconnectRequest(BaseModel):
    business_id: str


@router.post("/disconnect")
async def disconnect_google_calendar(
    request: DisconnectRequest,
    db: AsyncSession = Depends(get_db),
) -> GoogleCalendarAuthSuccess:
    """
    Disconnect Google Calendar from business
    
    Clears all stored credentials
    """
    # Verify business exists
    result = await db.execute(select(Business).where(Business.id == request.business_id))
    business = result.scalar_one_or_none()
    
    if not business:
        raise HTTPException(status_code=403, detail="Business not found")
    
    try:
        # Clear all Google Calendar credentials
        business.google_calendar_id = None
        business.google_refresh_token = None
        business.google_token_expires_at = None
        
        db.add(business)
        await db.commit()
        
        logger.info(f"Disconnected Google Calendar for business {request.business_id}")
        
        return GoogleCalendarAuthSuccess(
            success=True,
            message="Google Calendar disconnected successfully"
        )
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to disconnect Google Calendar for business {request.business_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to disconnect Google Calendar")
