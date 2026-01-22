from __future__ import annotations

import argparse
import asyncio
import json

from app.tools.tool_router import ToolRouter


async def run_smoke(
    business_id: str,
    customer_phone: str,
    topic: str,
) -> None:
    router = ToolRouter()

    latest = await router.execute(
        "get_latest_booking",
        {"customer_phone": customer_phone},
        business_id=business_id,
        caller_phone=customer_phone,
    )
    policies = await router.execute(
        "get_policies",
        {"topic": topic},
        business_id=business_id,
    )
    faqs = await router.execute(
        "get_faqs",
        {"topic": topic},
        business_id=business_id,
    )

    print(json.dumps({
        "latest_booking": latest,
        "policies": policies,
        "faqs": faqs,
    }, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test tool router against the DB.")
    parser.add_argument("--business-id", required=True, help="Business UUID")
    parser.add_argument("--customer-phone", required=True, help="Customer phone number")
    parser.add_argument("--topic", required=True, help="Policy/FAQ topic")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run_smoke(args.business_id, args.customer_phone, args.topic))


if __name__ == "__main__":
    main()
