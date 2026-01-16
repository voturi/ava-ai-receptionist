# Deployment Guide
## AI Receptionist SaaS - Production Deployment & Operations

Complete guide for deploying and operating the AI Receptionist platform in production.

---

## Table of Contents
1. [Infrastructure Overview](#infrastructure-overview)
2. [Environment Setup](#environment-setup)
3. [Initial Deployment](#initial-deployment)
4. [CI/CD Pipeline](#cicd-pipeline)
5. [Database Management](#database-management)
6. [Monitoring & Alerts](#monitoring--alerts)
7. [Backup & Recovery](#backup--recovery)
8. [Scaling Strategy](#scaling-strategy)
9. [Security Checklist](#security-checklist)
10. [Incident Response](#incident-response)

---

## Infrastructure Overview

### Production Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLOUDFLARE                            │
│                    (DNS + DDoS Protection)                   │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┴───────────────┐
         │                               │
┌────────▼────────┐             ┌───────▼────────┐
│   Vercel Edge   │             │  Railway/      │
│   (Frontend)    │             │  Render        │
│                 │             │  (Backend)     │
│  - Next.js SSR  │             │                │
│  - Static CDN   │◄────────────┤  - FastAPI     │
│  - Edge Funcs   │   API calls │  - Workers     │
└─────────────────┘             │  - Background  │
                                │    Jobs        │
                                └────────┬───────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    │                    │                    │
           ┌────────▼────────┐  ┌───────▼──────┐  ┌─────────▼────────┐
           │   Supabase      │  │   Upstash    │  │   External APIs  │
           │   (Postgres)    │  │   (Redis)    │  │                  │
           │                 │  │              │  │  - Twilio        │
           │  - Database     │  │  - Cache     │  │  - OpenAI        │
           │  - Realtime     │  │  - Sessions  │  │  - Deepgram      │
           │  - Auth         │  │  - Queue     │  │  - SendGrid      │
           │  - Storage      │  │              │  │  - Stripe        │
           └─────────────────┘  └──────────────┘  └──────────────────┘
```

### Service Providers

| Component | Provider | Tier | Monthly Cost |
|-----------|----------|------|--------------|
| Frontend Hosting | Vercel | Pro | $20 |
| Backend Hosting | Railway | Pro | $20 |
| Database | Supabase | Pro | $25 |
| Cache/Queue | Upstash | Pro | $10 |
| DNS/CDN | Cloudflare | Free | $0 |
| Error Tracking | Sentry | Team | $26 |
| Monitoring | Better Stack | Starter | $15 |
| **Total** | | | **$116/month** |

*At 10 customers, infrastructure = 3.8% of revenue ($3,000 MRR)*

---

## Environment Setup

### Required Environment Variables

#### Backend (.env)
```bash
# Application
APP_ENV=production
APP_NAME="AI Receptionist"
API_BASE_URL=https://api.yourdomain.com
FRONTEND_URL=https://app.yourdomain.com

# Database
DATABASE_URL=postgresql://user:pass@host:5432/dbname
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=10

# Redis
REDIS_URL=redis://default:pass@host:6379

# Supabase
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# AI Services
OPENAI_API_KEY=sk-proj-xxxxx
OPENAI_MODEL=gpt-4-turbo
OPENAI_MAX_TOKENS=1000

DEEPGRAM_API_KEY=xxxxx
ELEVENLABS_API_KEY=xxxxx

# Twilio
TWILIO_ACCOUNT_SID=ACxxxxx
TWILIO_AUTH_TOKEN=xxxxx
TWILIO_PHONE_NUMBER=+61280001234

# Email
SENDGRID_API_KEY=SG.xxxxx
SENDGRID_FROM_EMAIL=noreply@yourdomain.com

# Payments
STRIPE_SECRET_KEY=sk_live_xxxxx
STRIPE_PUBLISHABLE_KEY=pk_live_xxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxx

# Monitoring
SENTRY_DSN=https://xxxxx@sentry.io/xxxxx
SENTRY_ENVIRONMENT=production

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

#### Frontend (.env.production)
```bash
# API
NEXT_PUBLIC_API_URL=https://api.yourdomain.com
NEXT_PUBLIC_WS_URL=wss://api.yourdomain.com

# Supabase
NEXT_PUBLIC_SUPABASE_URL=https://xxxxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# Analytics
NEXT_PUBLIC_POSTHOG_KEY=phc_xxxxx
NEXT_PUBLIC_POSTHOG_HOST=https://app.posthog.com

# Stripe
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_live_xxxxx

# Monitoring
NEXT_PUBLIC_SENTRY_DSN=https://xxxxx@sentry.io/xxxxx
```

---

## Initial Deployment

### Pre-Deployment Checklist

- [ ] Domain registered and DNS configured
- [ ] SSL certificates generated (automatic with Vercel/Railway)
- [ ] All environment variables set
- [ ] Database migrations run
- [ ] Seed data loaded (if needed)
- [ ] External services configured (Twilio, OpenAI, etc.)
- [ ] Monitoring tools setup
- [ ] Backup strategy configured

### Step 1: Deploy Database (Supabase)

```bash
# 1. Create Supabase project
# Go to https://supabase.com/dashboard → New Project

# 2. Run migrations
# Connect to Supabase database URL
export DATABASE_URL="postgresql://..."

# Run migrations
cd backend
alembic upgrade head

# 3. Set up Row Level Security (RLS)
# Run security policies from project_plan.md

# 4. Configure Realtime
# Enable Realtime for tables: calls, bookings
# Go to Database → Replication → Enable for tables

# 5. Set up Storage
# Create buckets: call-recordings, business-assets
```

### Step 2: Deploy Backend (Railway)

```bash
# 1. Install Railway CLI
npm install -g @railway/cli

# 2. Login
railway login

# 3. Initialize project
cd backend
railway init

# 4. Set environment variables
railway variables set DATABASE_URL="postgresql://..."
railway variables set OPENAI_API_KEY="sk-..."
# ... set all backend env vars

# 5. Deploy
railway up

# 6. Get deployment URL
railway domain

# 7. Test health endpoint
curl https://your-backend.railway.app/health
```

**Alternative: Deploy to Render**
```bash
# 1. Create render.yaml
cat > render.yaml << EOF
services:
  - type: web
    name: ai-receptionist-api
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: DATABASE_URL
        sync: false
      - key: OPENAI_API_KEY
        sync: false
EOF

# 2. Connect GitHub repo on Render dashboard
# 3. Deploy automatically on push
```

### Step 3: Deploy Frontend (Vercel)

```bash
# 1. Install Vercel CLI
npm install -g vercel

# 2. Login
vercel login

# 3. Deploy to production
cd frontend
vercel --prod

# 4. Set environment variables
vercel env add NEXT_PUBLIC_API_URL production
vercel env add NEXT_PUBLIC_SUPABASE_URL production
# ... set all frontend env vars

# 5. Redeploy with env vars
vercel --prod

# 6. Configure custom domain
vercel domains add app.yourdomain.com
```

### Step 4: Configure DNS

```
# Cloudflare DNS Records

Type  | Name | Value | Proxy
------|------|-------|------
CNAME | app  | cname.vercel-dns.com | ✓ Proxied
CNAME | api  | your-backend.railway.app | ✓ Proxied
A     | @    | your-landing-page-ip | ✓ Proxied
```

### Step 5: Test Production Deployment

```bash
# Test API
curl https://api.yourdomain.com/health
# Expected: {"status": "healthy", "version": "1.0.0"}

# Test frontend
curl -I https://app.yourdomain.com
# Expected: HTTP/2 200

# Test Twilio webhook
# Make test call to Twilio number
# Check logs for successful webhook

# Test real-time
# Open dashboard, make call, verify live update

# Test authentication
# Sign up, log in, verify JWT token working
```

---

## CI/CD Pipeline

### GitHub Actions Workflow

#### Backend CI/CD (.github/workflows/backend.yml)

```yaml
name: Backend CI/CD

on:
  push:
    branches: [main, dev]
    paths:
      - 'backend/**'
  pull_request:
    branches: [main]
    paths:
      - 'backend/**'

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          cd backend
          pip install -r requirements.txt
          pip install -r requirements-dev.txt
      
      - name: Run linters
        run: |
          cd backend
          black --check .
          ruff check .
      
      - name: Run tests
        env:
          DATABASE_URL: postgresql://postgres:postgres@localhost:5432/test
        run: |
          cd backend
          pytest --cov=app --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./backend/coverage.xml
  
  deploy:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Deploy to Railway
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
        run: |
          npm install -g @railway/cli
          railway up --service backend
```

#### Frontend CI/CD (.github/workflows/frontend.yml)

```yaml
name: Frontend CI/CD

on:
  push:
    branches: [main, dev]
    paths:
      - 'frontend/**'
  pull_request:
    branches: [main]
    paths:
      - 'frontend/**'

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Node.js
        uses: actions/setup-node@v3
        with:
          node-version: '18'
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json
      
      - name: Install dependencies
        run: |
          cd frontend
          npm ci
      
      - name: Run linter
        run: |
          cd frontend
          npm run lint
      
      - name: Type check
        run: |
          cd frontend
          npm run type-check
      
      - name: Run tests
        run: |
          cd frontend
          npm test
      
      - name: Build
        run: |
          cd frontend
          npm run build
  
  deploy:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Deploy to Vercel
        env:
          VERCEL_TOKEN: ${{ secrets.VERCEL_TOKEN }}
          VERCEL_ORG_ID: ${{ secrets.VERCEL_ORG_ID }}
          VERCEL_PROJECT_ID: ${{ secrets.VERCEL_PROJECT_ID }}
        run: |
          npm install -g vercel
          cd frontend
          vercel pull --yes --environment=production --token=$VERCEL_TOKEN
          vercel build --prod --token=$VERCEL_TOKEN
          vercel deploy --prebuilt --prod --token=$VERCEL_TOKEN
```

### Deployment Stages

```
Feature Branch → Dev Branch → Main Branch
                     ↓             ↓
                  Staging      Production
                  
Merge to dev  → Auto-deploy to staging
Merge to main → Auto-deploy to production (after tests pass)
```

---

## Database Management

### Running Migrations

```bash
# Development
alembic upgrade head

# Production (via Railway/Render)
railway run alembic upgrade head

# Check current version
alembic current

# Rollback one version
alembic downgrade -1

# View migration history
alembic history
```

### Creating Migrations

```bash
# Auto-generate migration from model changes
alembic revision --autogenerate -m "Add customer_tier column"

# Create empty migration for data changes
alembic revision -m "Backfill customer tiers"

# Edit generated file in alembic/versions/
# Always review auto-generated migrations!
```

### Database Backup

**Automated Backups (Supabase)**:
- Daily automatic backups (retained for 7 days on Pro plan)
- Point-in-time recovery
- Configure in Supabase Dashboard → Database → Backups

**Manual Backup**:
```bash
# Full database dump
pg_dump $DATABASE_URL > backup_$(date +%Y%m%d).sql

# Restore from backup
psql $DATABASE_URL < backup_20260115.sql

# Backup specific tables
pg_dump $DATABASE_URL -t calls -t bookings > critical_tables.sql
```

---

## Monitoring & Alerts

### Metrics to Monitor

#### Application Metrics (Sentry)

```python
# Instrument key functions
import sentry_sdk

@sentry_sdk.trace
async def handle_incoming_call(business_id: str):
    with sentry_sdk.start_transaction(op="voice", name="handle_incoming_call"):
        # ... your code
        
        # Track custom metrics
        sentry_sdk.set_tag("business_id", business_id)
        sentry_sdk.set_context("call_details", {
            "caller_phone": phone,
            "duration": duration
        })
```

**Key Metrics**:
- Error rate (target: <1%)
- Response time (p95 <500ms)
- Call success rate (target: >95%)
- Booking conversion rate (target: >70%)

#### Infrastructure Metrics (Better Stack / Railway Dashboard)

- CPU usage (alert if >80%)
- Memory usage (alert if >85%)
- Disk usage (alert if >90%)
- Request rate
- Database connections

### Alert Configuration

**Sentry Alerts**:
```yaml
# .sentry/alerts.yaml
- name: High Error Rate
  conditions:
    - event_frequency: 
        comparison_type: count
        value: 10
        interval: 1m
  actions:
    - email
    - slack
  
- name: Slow API Response
  conditions:
    - performance_duration:
        comparison_type: above
        value: 2000  # 2 seconds
  actions:
    - slack
```

**Health Check Endpoint**:
```python
@app.get("/health")
async def health_check():
    """
    Health check endpoint for monitoring
    """
    checks = {
        "database": await check_database(),
        "redis": await check_redis(),
        "openai": await check_openai_api(),
        "twilio": await check_twilio_api()
    }
    
    all_healthy = all(checks.values())
    
    return {
        "status": "healthy" if all_healthy else "degraded",
        "timestamp": datetime.now().isoformat(),
        "checks": checks,
        "version": app.version
    }

async def check_database():
    try:
        await db.execute("SELECT 1")
        return True
    except:
        return False
```

**UptimeRobot Configuration**:
- Monitor: https://api.yourdomain.com/health
- Interval: 5 minutes
- Alert: Email + Slack if down
- Expected keyword: "healthy"

---

## Backup & Recovery

### Backup Strategy

**Daily Automated Backups**:
- Database: Supabase automatic backups (7-day retention)
- Environment configs: Stored in 1Password/secure vault
- Code: GitHub (source of truth)

**Weekly Manual Backups**:
```bash
#!/bin/bash
# scripts/backup.sh

DATE=$(date +%Y%m%d)
BACKUP_DIR="backups/$DATE"

mkdir -p $BACKUP_DIR

# Database
pg_dump $DATABASE_URL > $BACKUP_DIR/database.sql

# Environment variables (encrypted)
gpg --encrypt --recipient your@email.com .env > $BACKUP_DIR/env.gpg

# Upload to S3
aws s3 sync $BACKUP_DIR s3://your-backups-bucket/$DATE/
```

### Disaster Recovery

**Recovery Time Objective (RTO)**: 2 hours
**Recovery Point Objective (RPO)**: 24 hours

**Recovery Procedure**:
```bash
# 1. Restore database
psql $NEW_DATABASE_URL < backup.sql

# 2. Update environment variables
# Point DATABASE_URL to restored database

# 3. Redeploy services
railway up --service backend
vercel --prod

# 4. Verify functionality
curl https://api.yourdomain.com/health

# 5. Test critical paths
# - Make test call
# - Create test booking
# - Verify dashboard loads

# 6. Monitor error logs for 1 hour
```

---

## Scaling Strategy

### Current Capacity (Month 1-3)

```
Single Backend Instance:
├─ Handles: 1,000 calls/day (~12 concurrent)
├─ CPU: 1 core @ 50% avg
├─ Memory: 2GB
└─ Cost: $20/month

Database:
├─ Supabase Pro
├─ Handles: 10,000 connections
└─ Cost: $25/month

Total: $45/month for infrastructure
Supports: ~30 customers @ 30 calls/day each
```

### Scaling Triggers

**Scale Backend When**:
- CPU usage >80% for 10+ minutes
- Response time p95 >1s
- Error rate >2%
- Traffic: 50+ concurrent calls

**Horizontal Scaling (Railway)**:
```bash
# Add replica
railway scale --replicas 2

# Configure load balancer (automatic)
# Railway handles this

# Cost: $20 → $40/month
# Capacity: 1,000 calls/day → 2,000 calls/day
```

### Database Scaling

**Vertical Scaling**:
```
Supabase Pro → Supabase Team
$25/month → $599/month
10GB → 100GB
Supports: 100+ customers
```

**Read Replicas** (if needed at 150+ customers):
```python
# Configure read replica
READ_DATABASE_URL = os.getenv("READ_DATABASE_URL")

# Use for read-only queries
analytics = await db.execute(
    "SELECT * FROM daily_analytics",
    connection=read_replica
)
```

### Caching Strategy for Scale

```python
# Cache expensive queries
@cache(ttl=300)  # 5 minutes
async def get_business_stats(business_id: str):
    return await calculate_stats(business_id)

# Cache external API calls
@cache(ttl=60)  # 1 minute
async def get_calendar_availability(date: str):
    return await fresha_client.get_availability(date)

# Invalidate cache on updates
async def create_booking(...):
    booking = await db.create_booking(...)
    await cache.invalidate(f"business_stats:{business_id}")
    return booking
```

---

## Security Checklist

### Pre-Launch Security

- [ ] All secrets in environment variables (not code)
- [ ] Database uses SSL connections
- [ ] Row-level security (RLS) enabled on all tables
- [ ] API endpoints require authentication (except webhooks)
- [ ] Rate limiting configured (100 req/min per IP)
- [ ] CORS properly configured (whitelist frontend domain)
- [ ] Input validation on all endpoints
- [ ] SQL injection prevention (use parameterized queries)
- [ ] XSS prevention (sanitize user input)
- [ ] CSRF tokens on forms
- [ ] HTTPS enforced (redirect HTTP → HTTPS)
- [ ] Security headers configured
- [ ] Dependencies scanned for vulnerabilities
- [ ] Secrets rotation schedule established

### Security Headers

```python
# app/middleware/security.py
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.cors import CORSMiddleware

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://app.yourdomain.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Security headers
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response
```

### Rate Limiting

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.get("/api/calls")
@limiter.limit("100/minute")
async def get_calls(request: Request):
    # ... your code
    pass
```

### Dependency Scanning

```bash
# Scan Python dependencies
pip install safety
safety check

# Scan Node dependencies
npm audit

# Auto-fix vulnerabilities
npm audit fix
```

---

## Incident Response

### Incident Severity Levels

**P0 - Critical (Response: Immediate)**:
- All voice calls failing
- Database down
- Payment processing down
- Security breach

**P1 - High (Response: <1 hour)**:
- Calls failing for specific businesses
- Dashboard not loading
- Degraded performance (>5s response time)

**P2 - Medium (Response: <4 hours)**:
- SMS/email notifications delayed
- Analytics not updating
- Minor bugs affecting UX

**P3 - Low (Response: <24 hours)**:
- Cosmetic issues
- Feature requests
- Non-critical bugs

### Incident Response Procedure

**1. Detection**:
- Automated alerts (Sentry, Better Stack, UptimeRobot)
- Customer reports
- Manual discovery

**2. Assessment**:
```bash
# Check service status
railway status
vercel inspect deployment-url

# Check logs
railway logs --tail 100
vercel logs

# Check metrics
# Open Sentry dashboard
# Check error rate, affected users
```

**3. Communication**:
```markdown
# Status page update (statuspage.io or manual)
🔴 Investigating: Voice calls failing for some customers

We're aware of an issue where some customers are experiencing
failed voice calls. Our team is investigating.

Updates will be posted here every 15 minutes.

Last updated: 3:45pm AEDT
```

**4. Mitigation**:
```bash
# Common fixes:

# Rollback deployment
railway rollback

# Restart service
railway restart

# Scale up (if capacity issue)
railway scale --replicas 3

# Check and fix database
railway run alembic upgrade head
```

**5. Resolution**:
```markdown
# Status page final update
✅ Resolved: Voice calls restored

The issue has been resolved. All voice calls are now working normally.

Root cause: Database connection pool exhausted during traffic spike.
Fix: Increased connection pool size from 20 to 50.

We apologize for any inconvenience.
```

**6. Post-Mortem**:
```markdown
# Incident Post-Mortem Template

## Incident Summary
**Date**: January 15, 2026
**Duration**: 3:30pm - 4:15pm AEDT (45 minutes)
**Severity**: P1
**Impact**: 15 businesses affected, ~60 missed calls

## Root Cause
Database connection pool (20 connections) exhausted during traffic spike.

## Timeline
- 3:30pm: First alert from UptimeRobot
- 3:32pm: Confirmed voice calls failing
- 3:35pm: Posted status update
- 3:40pm: Identified connection pool issue
- 3:50pm: Increased pool size to 50
- 3:55pm: Deployed fix
- 4:00pm: Verified resolution
- 4:15pm: Closed incident

## Resolution
Increased DATABASE_POOL_SIZE from 20 to 50.

## Preventive Measures
1. Set up alert for connection pool usage >80%
2. Implement connection pooling metrics
3. Add auto-scaling based on database connections
4. Load test with 2x expected traffic

## Action Items
- [ ] Implement connection pool monitoring (Owner: @engineer, Due: Jan 20)
- [ ] Add auto-scaling rules (Owner: @engineer, Due: Jan 25)
- [ ] Conduct load testing (Owner: @engineer, Due: Feb 1)
```

---

## Deployment Runbook

### Standard Deployment

```bash
# 1. Create release branch
git checkout main
git pull origin main
git checkout -b release/v1.2.0

# 2. Update version
# Update version in package.json, __init__.py

# 3. Run tests locally
cd backend && pytest
cd frontend && npm test

# 4. Create PR to main
git push origin release/v1.2.0
# Open PR on GitHub

# 5. Merge after approval
# GitHub Actions will auto-deploy

# 6. Verify deployment
curl https://api.yourdomain.com/health
# Check dashboard loads

# 7. Tag release
git tag v1.2.0
git push origin v1.2.0

# 8. Monitor for 30 minutes
# Watch Sentry for errors
# Check customer activity
```

### Hotfix Deployment

```bash
# 1. Create hotfix branch from main
git checkout main
git checkout -b hotfix/fix-critical-bug

# 2. Make minimal fix
# Only change what's necessary

# 3. Test fix
pytest tests/test_affected_area.py

# 4. Deploy immediately
git push origin hotfix/fix-critical-bug

# Merge to main (skip PR if critical)
git checkout main
git merge hotfix/fix-critical-bug
git push origin main

# 5. Verify fix
# Test affected functionality

# 6. Create post-mortem
# Document what happened and how to prevent
```

### Rollback Procedure

```bash
# If deployment causes issues:

# 1. Rollback backend
railway rollback

# 2. Rollback frontend
vercel rollback

# 3. Verify services
curl https://api.yourdomain.com/health

# 4. If database migration issue
alembic downgrade -1

# 5. Communicate to team
# Post in Slack: "Rolled back v1.2.0 due to [issue]"

# 6. Investigate and fix
# Don't deploy again until root cause fixed
```

---

## Operations Checklist

### Daily

- [ ] Check Sentry for new errors
- [ ] Review monitoring dashboards
- [ ] Respond to customer support tickets
- [ ] Check deployment status

### Weekly

- [ ] Review technical debt
- [ ] Update dependencies (if security patches)
- [ ] Backup environment configs
- [ ] Review metrics vs targets

### Monthly

- [ ] Full backup test (restore to staging)
- [ ] Security audit (dependency scan, review logs)
- [ ] Capacity planning (check growth trends)
- [ ] Cost optimization review
- [ ] Update runbooks with learnings

---

## Cost Optimization

### Current Costs (10 customers)

```
Infrastructure:        $116/month
External APIs:         $200/month (Twilio, OpenAI, etc.)
Total:                 $316/month

Revenue:               $3,000/month
Gross Margin:          89%
```

### Cost Optimization Strategies

**1. API Costs**:
```python
# Cache OpenAI responses for common questions
@cache(ttl=3600)
async def get_ai_response(prompt: str):
    # Costs $0.02 per call
    # Caching saves 50% = $100/month saved
    pass

# Use GPT-3.5 for simple queries
if is_simple_query(text):
    model = "gpt-3.5-turbo"  # $0.002 per call
else:
    model = "gpt-4-turbo"     # $0.02 per call
```

**2. Twilio Costs**:
```python
# Buy phone numbers in bulk (discount)
# Use shorter calls (optimize prompt)
# Cache TTS responses for greetings
```

**3. Database Costs**:
```python
# Archive old data (>6 months) to cold storage
# Use database views for complex queries (vs compute)
# Implement data retention policy
```

---

## Questions or Issues?

For deployment issues, contact:
- **Primary**: @founder (Slack, Phone)
- **Escalation**: Open incident in GitHub Issues
- **Emergency**: Use PagerDuty (if configured)

---

**Last Updated**: January 15, 2026
**Maintainer**: [Your Name]
**Version**: 1.0