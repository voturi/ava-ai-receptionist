# Contributing Guide
## AI Receptionist SaaS - Development Standards & Workflow

Welcome! This guide will help you contribute effectively to the codebase.

---

## Table of Contents
1. [Getting Started](#getting-started)
2. [Development Workflow](#development-workflow)
3. [Code Standards](#code-standards)
4. [Testing Guidelines](#testing-guidelines)
5. [Git Workflow](#git-workflow)
6. [Pull Request Process](#pull-request-process)
7. [Common Tasks](#common-tasks)
8. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 18+
- PostgreSQL 15+ (or Supabase account)
- Redis (or Upstash account)
- Docker & Docker Compose (optional but recommended)

### First-Time Setup

#### 1. Clone the Repository
```bash
git clone https://github.com/your-org/ai-receptionist.git
cd ai-receptionist
```

#### 2. Backend Setup
```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Development dependencies

# Copy environment template
cp .env.example .env

# Edit .env with your credentials
# Required: DATABASE_URL, OPENAI_API_KEY, TWILIO_ACCOUNT_SID, etc.
```

#### 3. Frontend Setup
```bash
cd frontend

# Install dependencies
npm install

# Copy environment template
cp .env.local.example .env.local

# Edit .env.local with your API URLs
```

#### 4. Database Setup
```bash
cd backend

# Run migrations
alembic upgrade head

# Seed development data (optional)
python scripts/seed_dev_data.py
```

#### 5. Start Development Servers

**Terminal 1 - Backend:**
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

**Terminal 2 - Frontend:**
```bash
cd frontend
npm run dev
```

**Terminal 3 - Redis (if local):**
```bash
redis-server
```

#### 6. Verify Setup
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Frontend: http://localhost:3000
- Test call: Use Twilio Console to simulate incoming call

---

## Development Workflow

### Daily Workflow

```bash
# 1. Start of day - sync with main
git checkout main
git pull origin main

# 2. Create feature branch
git checkout -b feature/your-feature-name

# 3. Make changes
# ... code, test, commit ...

# 4. Push and create PR
git push origin feature/your-feature-name
# Create PR on GitHub

# 5. After PR merged, clean up
git checkout main
git pull origin main
git branch -d feature/your-feature-name
```

### Running the Full Stack with Docker (Alternative)

```bash
# Start all services
docker-compose up

# Run in background
docker-compose up -d

# View logs
docker-compose logs -f

# Stop all services
docker-compose down
```

---

## Code Standards

### Backend (Python/FastAPI)

#### File Structure
```
backend/
├── app/
│   ├── main.py              # FastAPI app initialization
│   ├── config.py            # Configuration management
│   ├── models/              # Database models (SQLAlchemy)
│   │   ├── business.py
│   │   ├── call.py
│   │   └── booking.py
│   ├── schemas/             # Pydantic schemas (request/response)
│   │   ├── business.py
│   │   └── call.py
│   ├── api/                 # API endpoints
│   │   ├── v1/
│   │   │   ├── voice.py     # Twilio webhooks
│   │   │   ├── businesses.py
│   │   │   └── calls.py
│   │   └── deps.py          # Dependency injection
│   ├── services/            # Business logic
│   │   ├── voice_service.py
│   │   ├── booking_service.py
│   │   └── ai_service.py
│   ├── integrations/        # External API clients
│   │   ├── twilio.py
│   │   ├── openai_client.py
│   │   └── fresha.py
│   ├── core/                # Core utilities
│   │   ├── database.py
│   │   ├── redis.py
│   │   └── logging.py
│   └── utils/               # Helper functions
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── alembic/                 # Database migrations
├── scripts/                 # Utility scripts
└── requirements.txt
```

#### Naming Conventions
```python
# Files: snake_case
voice_service.py
booking_service.py

# Classes: PascalCase
class VoiceService:
    pass

class BookingRequest:
    pass

# Functions/Variables: snake_case
def create_booking(business_id: str):
    customer_name = "John Doe"
    pass

# Constants: UPPER_SNAKE_CASE
MAX_RETRY_ATTEMPTS = 3
DEFAULT_VOICE_ID = "Polly.Nicole"

# Private methods: _prefix
def _internal_helper(self):
    pass
```

#### Type Hints (Required)
```python
# ✅ GOOD
def create_booking(
    business_id: str,
    customer_name: str,
    service: str,
    datetime: datetime
) -> Booking:
    pass

async def get_business(business_id: str) -> Optional[Business]:
    pass

# ❌ BAD - No type hints
def create_booking(business_id, customer_name, service, datetime):
    pass
```

#### API Endpoint Pattern
```python
from fastapi import APIRouter, Depends, HTTPException
from app.schemas.booking import BookingCreate, BookingResponse
from app.services.booking_service import BookingService
from app.api.deps import get_current_business

router = APIRouter()

@router.post("/bookings", response_model=BookingResponse)
async def create_booking(
    booking: BookingCreate,
    business_id: str = Depends(get_current_business),
    service: BookingService = Depends()
):
    """
    Create a new booking.
    
    - **business_id**: ID of the business (from auth token)
    - **booking**: Booking details (customer, service, datetime)
    """
    try:
        result = await service.create_booking(business_id, booking)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Booking creation failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
```

#### Error Handling Pattern
```python
from app.core.exceptions import (
    BusinessNotFoundError,
    InvalidBookingError,
    ExternalServiceError
)

# Service layer - raise domain exceptions
class BookingService:
    async def create_booking(self, business_id: str, data: BookingCreate):
        business = await self.db.get_business(business_id)
        if not business:
            raise BusinessNotFoundError(f"Business {business_id} not found")
        
        if data.booking_datetime < datetime.now():
            raise InvalidBookingError("Cannot book in the past")
        
        try:
            external_id = await self.fresha_client.create_booking(data)
        except FreshaAPIError as e:
            raise ExternalServiceError(f"Fresha booking failed: {e}")
        
        return await self.db.create_booking(data, external_id)

# API layer - convert to HTTP exceptions
@router.post("/bookings")
async def create_booking_endpoint(...):
    try:
        return await service.create_booking(...)
    except BusinessNotFoundError as e:
        raise HTTPException(404, detail=str(e))
    except InvalidBookingError as e:
        raise HTTPException(400, detail=str(e))
    except ExternalServiceError as e:
        logger.error(f"External service error: {e}")
        raise HTTPException(503, detail="Booking system temporarily unavailable")
```

#### Logging Standards
```python
import logging
from app.core.logging import get_logger

logger = get_logger(__name__)

# Log levels
logger.debug("Detailed diagnostic info")      # Development only
logger.info("Normal business event")          # Booking created, payment received
logger.warning("Unexpected but handled")      # Low confidence AI response
logger.error("Error requiring investigation") # API call failed
logger.critical("System failure")             # Database down

# Always include context
logger.error("Booking failed", extra={
    "business_id": business_id,
    "customer_phone": phone,
    "service": service,
    "error_type": type(e).__name__,
    "traceback": traceback.format_exc()
})
```

---

### Frontend (Next.js/React/TypeScript)

#### File Structure
```
frontend/
├── app/
│   ├── layout.tsx           # Root layout
│   ├── page.tsx             # Landing page
│   ├── (auth)/              # Auth group
│   │   ├── login/
│   │   └── signup/
│   └── dashboard/           # Dashboard group
│       ├── layout.tsx       # Dashboard shell
│       ├── page.tsx         # Overview
│       ├── calls/
│       ├── bookings/
│       └── settings/
├── components/
│   ├── ui/                  # shadcn components
│   ├── dashboard/           # Dashboard-specific
│   │   ├── StatCard.tsx
│   │   ├── CallCard.tsx
│   │   └── BookingCalendar.tsx
│   └── layout/
│       ├── Sidebar.tsx
│       └── Header.tsx
├── lib/
│   ├── api.ts               # API client
│   ├── supabase.ts          # Supabase client
│   └── utils.ts             # Helper functions
├── hooks/
│   ├── useAuth.ts
│   ├── useCalls.ts
│   └── useRealtime.ts
├── types/
│   ├── business.ts
│   ├── call.ts
│   └── booking.ts
└── styles/
    └── globals.css
```

#### Naming Conventions
```typescript
// Components: PascalCase
export const CallCard = ({ call }: CallCardProps) => {
  return <div>...</div>;
};

// Hooks: camelCase with 'use' prefix
export const useAuth = () => {
  const [user, setUser] = useState(null);
  return { user, setUser };
};

// Types/Interfaces: PascalCase
interface CallCardProps {
  call: Call;
  onView?: (id: string) => void;
}

type CallStatus = 'booked' | 'inquiry' | 'missed';

// Constants: UPPER_SNAKE_CASE
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL;
const MAX_RETRIES = 3;
```

#### Component Pattern
```typescript
'use client';

import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Phone } from 'lucide-react';

interface StatCardProps {
  title: string;
  value: number;
  change?: string;
  icon?: React.ElementType;
  color?: 'cyan' | 'purple' | 'yellow';
}

export const StatCard = ({ 
  title, 
  value, 
  change, 
  icon: Icon = Phone,
  color = 'cyan' 
}: StatCardProps) => {
  const [displayValue, setDisplayValue] = useState(0);
  
  // Animate counter on mount
  useEffect(() => {
    animateValue(0, value, 1000, setDisplayValue);
  }, [value]);
  
  const colorClasses = {
    cyan: 'from-cyan-500/20 border-cyan-500/30',
    purple: 'from-purple-500/20 border-purple-500/30',
    yellow: 'from-yellow-500/20 border-yellow-500/30'
  };
  
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ scale: 1.02 }}
      className={`bg-gradient-to-br ${colorClasses[color]} backdrop-blur-xl border rounded-2xl p-6 cursor-pointer`}
    >
      <div className="flex items-center justify-between mb-4">
        <div className="p-3 bg-white/10 rounded-xl">
          <Icon className="w-5 h-5 text-white" />
        </div>
        {change && (
          <span className="text-emerald-400 text-xs font-bold">
            {change}
          </span>
        )}
      </div>
      <div className="text-5xl font-bold text-white mb-1">
        {displayValue}
      </div>
      <div className="text-gray-300 text-sm font-semibold">{title}</div>
    </motion.div>
  );
};
```

#### API Client Pattern
```typescript
// lib/api.ts
import { supabase } from './supabase';

class APIClient {
  private baseURL: string;
  
  constructor() {
    this.baseURL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  }
  
  private async getAuthToken(): Promise<string> {
    const { data: { session } } = await supabase.auth.getSession();
    return session?.access_token || '';
  }
  
  async get<T>(path: string): Promise<T> {
    const token = await this.getAuthToken();
    const response = await fetch(`${this.baseURL}${path}`, {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      }
    });
    
    if (!response.ok) {
      throw new APIError(response.status, await response.text());
    }
    
    return response.json();
  }
  
  async post<T>(path: string, data: any): Promise<T> {
    const token = await this.getAuthToken();
    const response = await fetch(`${this.baseURL}${path}`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(data)
    });
    
    if (!response.ok) {
      throw new APIError(response.status, await response.text());
    }
    
    return response.json();
  }
}

export const api = new APIClient();

// Usage in components
import { api } from '@/lib/api';

const calls = await api.get<Call[]>('/api/calls?limit=20');
const booking = await api.post<Booking>('/api/bookings', bookingData);
```

---

## Testing Guidelines

### Backend Testing

#### Unit Tests
```python
# tests/unit/services/test_booking_service.py
import pytest
from datetime import datetime, timedelta
from app.services.booking_service import BookingService
from app.core.exceptions import InvalidBookingError

@pytest.fixture
def booking_service():
    return BookingService(db=mock_db, fresha_client=mock_fresha)

def test_create_booking_success(booking_service):
    """Test successful booking creation"""
    booking_data = {
        "customer_name": "John Doe",
        "service": "haircut",
        "datetime": datetime.now() + timedelta(days=1)
    }
    
    result = await booking_service.create_booking("biz_123", booking_data)
    
    assert result.customer_name == "John Doe"
    assert result.status == "pending"

def test_create_booking_past_date_raises_error(booking_service):
    """Test that booking in past raises error"""
    booking_data = {
        "customer_name": "John Doe",
        "service": "haircut",
        "datetime": datetime.now() - timedelta(days=1)  # Past
    }
    
    with pytest.raises(InvalidBookingError, match="Cannot book in the past"):
        await booking_service.create_booking("biz_123", booking_data)
```

#### Integration Tests
```python
# tests/integration/test_voice_api.py
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_incoming_call_creates_call_record():
    """Test that Twilio webhook creates call in database"""
    response = client.post(
        "/voice/incoming/biz_123",
        data={
            "From": "+61412345678",
            "CallSid": "CA1234567890",
            "To": "+61280001234"
        }
    )
    
    assert response.status_code == 200
    assert "<?xml version" in response.text  # TwiML response
    
    # Verify call record created
    call = db.get_call_by_sid("CA1234567890")
    assert call is not None
    assert call.caller_phone == "+61412345678"
```

#### Running Tests
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/unit/services/test_booking_service.py

# Run tests matching pattern
pytest -k "test_booking"

# Run with verbose output
pytest -v
```

---

### Frontend Testing

#### Component Tests (Vitest + Testing Library)
```typescript
// components/dashboard/StatCard.test.tsx
import { render, screen } from '@testing-library/react';
import { StatCard } from './StatCard';

describe('StatCard', () => {
  it('renders title and value', () => {
    render(<StatCard title="Total Calls" value={42} />);
    
    expect(screen.getByText('Total Calls')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
  });
  
  it('displays change indicator when provided', () => {
    render(<StatCard title="Total Calls" value={42} change="+23%" />);
    
    expect(screen.getByText('+23%')).toBeInTheDocument();
  });
});
```

#### Running Frontend Tests
```bash
# Run tests
npm test

# Run with coverage
npm run test:coverage

# Run in watch mode
npm run test:watch
```

---

## Git Workflow

### Branch Naming
```bash
# Features
feature/voice-booking
feature/dashboard-analytics
feature/whatsapp-integration

# Bug fixes
fix/sms-encoding-issue
fix/dashboard-loading-slow

# Refactoring
refactor/extract-booking-service
refactor/simplify-voice-handler

# Documentation
docs/api-endpoints
docs/deployment-guide
```

### Commit Message Format
```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `refactor`: Code refactoring
- `docs`: Documentation
- `test`: Adding tests
- `chore`: Maintenance tasks

**Examples:**
```bash
feat(voice): Add SMS confirmation after booking

- Send SMS to customer after successful booking
- Include booking details and business info
- Add retry logic for failed SMS

Closes #123

---

fix(dashboard): Resolve slow loading on calls page

Added index on calls.started_at column to speed up queries.
Load time reduced from 5s to 0.3s.

Fixes #156

---

refactor(booking): Extract booking validation logic

Moved validation from API handler to BookingService for reusability.
No functional changes.
```

### Commit Best Practices
```bash
# ✅ GOOD: Atomic commits
git add app/services/booking_service.py tests/unit/test_booking_service.py
git commit -m "feat(booking): Add booking validation logic"

git add app/api/v1/bookings.py
git commit -m "feat(api): Wire up booking validation in endpoint"

# ❌ BAD: Giant commits
git add .
git commit -m "stuff"

# ✅ GOOD: Descriptive
git commit -m "fix(voice): Handle missing customer phone gracefully"

# ❌ BAD: Vague
git commit -m "fix bug"
```

---

## Pull Request Process

### Before Creating PR

```bash
# 1. Sync with main
git checkout main
git pull origin main
git checkout your-feature-branch
git rebase main  # Or merge main if preferred

# 2. Run tests
pytest  # Backend
npm test  # Frontend

# 3. Run linters/formatters
black .  # Python
ruff check .  # Python linter
npm run lint  # Frontend

# 4. Push
git push origin your-feature-branch
```

### PR Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Refactoring
- [ ] Documentation

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Manually tested

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-reviewed code
- [ ] Commented complex logic
- [ ] Documentation updated
- [ ] No breaking changes (or documented)

## Screenshots (if UI changes)
[Add screenshots]

## Related Issues
Closes #123
```

### Review Process

**For Reviewer:**
1. Check code quality and style
2. Verify tests pass
3. Test locally if significant change
4. Approve or request changes

**For Author:**
1. Address all comments
2. Re-request review after changes
3. Don't merge until approved

### Merging
- Use "Squash and merge" for feature branches
- Use "Rebase and merge" for hotfixes
- Delete branch after merge

---

## Common Tasks

### Adding a New API Endpoint

1. **Create Pydantic schema** (`app/schemas/your_model.py`)
```python
from pydantic import BaseModel

class YourModelCreate(BaseModel):
    field1: str
    field2: int

class YourModelResponse(YourModelCreate):
    id: str
    created_at: datetime
```

2. **Add endpoint** (`app/api/v1/your_endpoint.py`)
```python
@router.post("/your-endpoint", response_model=YourModelResponse)
async def create_item(
    data: YourModelCreate,
    service: YourService = Depends()
):
    return await service.create(data)
```

3. **Register router** (`app/main.py`)
```python
from app.api.v1 import your_endpoint

app.include_router(your_endpoint.router, prefix="/api/v1", tags=["your-endpoint"])
```

4. **Add tests**
```python
def test_create_item():
    response = client.post("/api/v1/your-endpoint", json={...})
    assert response.status_code == 200
```

---

### Adding a Database Migration

```bash
# 1. Make changes to models in app/models/

# 2. Generate migration
alembic revision --autogenerate -m "Add new_column to businesses"

# 3. Review generated migration in alembic/versions/
# Edit if needed

# 4. Apply migration
alembic upgrade head

# 5. Test rollback
alembic downgrade -1
alembic upgrade head
```

---

### Adding a New Frontend Page

1. **Create page** (`app/dashboard/your-page/page.tsx`)
```typescript
export default function YourPage() {
  return (
    <div>
      <h1>Your Page</h1>
    </div>
  );
}
```

2. **Add to navigation** (`components/layout/Sidebar.tsx`)
```typescript
const navItems = [
  // ... existing items
  { name: 'Your Page', href: '/dashboard/your-page', icon: YourIcon }
];
```

3. **Fetch data** (if needed)
```typescript
'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

export default function YourPage() {
  const [data, setData] = useState(null);
  
  useEffect(() => {
    api.get('/api/your-endpoint').then(setData);
  }, []);
  
  return <div>{data && <YourComponent data={data} />}</div>;
}
```

---

## Troubleshooting

### Backend Issues

**Problem: Import errors**
```bash
# Solution: Reinstall dependencies
pip install -r requirements.txt

# Or recreate venv
rm -rf venv
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Problem: Database connection errors**
```bash
# Check DATABASE_URL in .env
echo $DATABASE_URL

# Test connection
psql $DATABASE_URL

# Run migrations
alembic upgrade head
```

**Problem: Tests failing**
```bash
# Clear pytest cache
pytest --cache-clear

# Run with verbose output
pytest -vv

# Run single test
pytest tests/unit/test_booking.py::test_create_booking -v
```

---

### Frontend Issues

**Problem: Module not found**
```bash
# Clear cache and reinstall
rm -rf node_modules .next
npm install

# If still issues, clear npm cache
npm cache clean --force
npm install
```

**Problem: Build errors**
```bash
# Check for TypeScript errors
npm run type-check

# Build locally to see errors
npm run build
```

**Problem: Environment variables not working**
```bash
# Restart dev server after changing .env.local
# Ensure variables are prefixed with NEXT_PUBLIC_ for client-side access
```

---

### Common Debug Commands

```bash
# Backend: Enable debug logging
export LOG_LEVEL=DEBUG
uvicorn app.main:app --reload

# Backend: Print SQL queries
export DATABASE_ECHO=1

# Frontend: Enable verbose logging
export NEXT_PUBLIC_LOG_LEVEL=debug

# Check running processes
lsof -i :8000  # Backend port
lsof -i :3000  # Frontend port

# Kill process on port
kill -9 $(lsof -t -i:8000)
```

---

## Questions or Issues?

- **Bugs**: Open an issue on GitHub
- **Questions**: Ask in team Slack channel
- **Urgent**: Ping @founder directly

---

**Last Updated**: January 15, 2026
**Maintainer**: [Your Name]