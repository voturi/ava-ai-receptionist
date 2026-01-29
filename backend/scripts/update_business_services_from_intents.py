from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

# Ensure the backend project root (the directory containing the "app" package)
# is on sys.path so this script can be executed from the repo root or backend/.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import AsyncSessionLocal
from app.services.db_service import DBService
from app.services.intent_profiles import get_issue_profiles


async def update_business_services(business_id: str) -> None:
    """Replace a business's services with entries derived from the intent CSV.

    Each row in "Intent Mapping - Sheet1.csv" becomes a structured service
    item on the Business.services JSON field, e.g.:

    {
        "id": "emergency_plumbing",
        "name": "Emergency Plumbing",
        "description": "Something’s gone wrong and I need help now.",
        "jobs_covered": ["Burst pipe", "Sewer blockage", ...],
    }
    """

    async with AsyncSessionLocal() as session:
        db_service = DBService(session)
        business = await db_service.get_business(business_id)
        if not business:
            print(f"❌ Business not found: {business_id}")
            return

        profiles = get_issue_profiles()
        if not profiles:
            print("⚠️ No intent profiles loaded from CSV; nothing to update.")
            return

        services: list[dict[str, Any]] = []
        for profile in profiles:
            # Prefer the customer-intent summary as a short description,
            # falling back to the purpose field.
            description = profile.customer_intent or profile.purpose
            services.append(
                {
                    "id": profile.id,
                    "name": profile.workflow,
                    "description": description,
                    "jobs_covered": profile.jobs_covered,
                }
            )

        await db_service.update_business(business_id, {"services": services})
        print(
            f"✅ Updated business {business_id} with {len(services)} "
            f"services from intent mapping CSV."
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Update a business's services from docs/Intent Mapping - Sheet1.csv "
            "using the intent profile loader."
        )
    )
    parser.add_argument("--business-id", required=True, help="Business UUID to update")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(update_business_services(args.business_id))


if __name__ == "__main__":
    main()
