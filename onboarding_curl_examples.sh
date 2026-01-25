#!/usr/bin/env bash
set -euo pipefail

API_BASE=${API_BASE:-http://localhost:8000}
BUSINESS_ID=${BUSINESS_ID:-}

# Create
curl -X POST "$API_BASE/admin/onboarding/tradies" \
  -H "Content-Type: application/json" \
  --data-binary @onboarding_payload_example.json

# Update (requires BUSINESS_ID)
if [[ -n "$BUSINESS_ID" ]]; then
  curl -X PUT "$API_BASE/admin/onboarding/tradies/$BUSINESS_ID" \
    -H "Content-Type: application/json" \
    --data-binary @onboarding_payload_example.json

  # Delete
  curl -X DELETE "$API_BASE/admin/onboarding/tradies/$BUSINESS_ID"
fi
