"""Google Calendar OAuth 2.0 Flow Handler"""

import os
import logging
from typing import Optional, Tuple
from datetime import datetime, timedelta
from urllib.parse import urlencode

import aiohttp
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# Get encryption key from env (same as app secrets key)
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", Fernet.generate_key())
cipher_suite = Fernet(ENCRYPTION_KEY)


class GoogleCalendarOAuth:
    """Handle Google Calendar OAuth 2.0 flow"""
    
    def __init__(self):
        self.client_id = os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        self.redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
        self.scopes = [
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.events",
        ]
        
        if not all([self.client_id, self.client_secret, self.redirect_uri]):
            logger.warning("Google Calendar OAuth credentials not configured")
    
    def get_authorization_url(self, business_id: str) -> str:
        """
        Generate the Google OAuth authorization URL
        
        Args:
            business_id: Business ID to pass as state parameter
            
        Returns:
            Authorization URL for user to visit
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",  # Get refresh token
            "prompt": "consent",  # Force consent screen
            "state": business_id,  # Pass business_id for security
        }
        
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    
    async def exchange_code_for_tokens(
        self, 
        code: str
    ) -> Tuple[str, str, int]:
        """
        Exchange authorization code for access and refresh tokens
        
        Args:
            code: Authorization code from OAuth callback
            
        Returns:
            Tuple of (access_token, refresh_token, expires_in_seconds)
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "code": code,
                        "redirect_uri": self.redirect_uri,
                        "grant_type": "authorization_code",
                    },
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Token exchange failed: {error_text}")
                        raise Exception(f"Failed to exchange code: {resp.status}")
                    
                    data = await resp.json()
                    
                    access_token = data.get("access_token")
                    refresh_token = data.get("refresh_token")
                    expires_in = data.get("expires_in", 3600)
                    
                    if not access_token:
                        raise Exception("No access token in response")
                    
                    logger.info(f"Successfully exchanged code for tokens")
                    return access_token, refresh_token, expires_in
                    
        except Exception as e:
            logger.error(f"OAuth token exchange error: {e}")
            raise
    
    async def refresh_access_token(self, refresh_token: str) -> Tuple[str, int]:
        """
        Use refresh token to get new access token
        
        Args:
            refresh_token: Refresh token from initial auth
            
        Returns:
            Tuple of (new_access_token, expires_in_seconds)
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Token refresh failed: {error_text}")
                        raise Exception(f"Failed to refresh token: {resp.status}")
                    
                    data = await resp.json()
                    access_token = data.get("access_token")
                    expires_in = data.get("expires_in", 3600)
                    
                    if not access_token:
                        raise Exception("No access token in response")
                    
                    logger.info(f"Successfully refreshed access token")
                    return access_token, expires_in
                    
        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            raise
    
    @staticmethod
    def encrypt_token(token: str) -> str:
        """Encrypt refresh token for storage"""
        return cipher_suite.encrypt(token.encode()).decode()
    
    @staticmethod
    def decrypt_token(encrypted_token: str) -> str:
        """Decrypt stored refresh token"""
        return cipher_suite.decrypt(encrypted_token.encode()).decode()


# Singleton instance
google_oauth = GoogleCalendarOAuth()
