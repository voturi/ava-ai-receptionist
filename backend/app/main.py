# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os

#Import Routers
from app.api.v1 import voice
from app.api.v1 import calls
from app.api.v1 import tts_admin
from app.api.v1 import media_stream

# Load environment variables
load_dotenv()

# Create FastAPI app
app = FastAPI(
    title="Digital Receptionist API",
    description="Voice Assistant for service businesses",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
#Include routers
app.include_router(voice.router, prefix="/voice", tags=["voice"])
app.include_router(calls.router, prefix="/api", tags=["calls"])
app.include_router(tts_admin.router, prefix="/admin/tts", tags=["tts"])
app.include_router(media_stream.router, prefix="/stream", tags=["streaming"])


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "AI Receptionist API",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "environment": os.getenv("APP_ENV", "unknown")
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", 8000)),
        reload=True
    )
