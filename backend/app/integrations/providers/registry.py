from __future__ import annotations

from typing import Any

from app.integrations.providers.base import BookingProvider
from app.integrations.providers.native import NativeBookingProvider


_PROVIDERS: dict[str, BookingProvider] = {
    "native": NativeBookingProvider(),
}


def resolve_provider(config: dict[str, Any] | None) -> BookingProvider:
    provider_name = "native"
    if config:
        provider_name = config.get("provider", "native")
    return _PROVIDERS.get(provider_name, _PROVIDERS["native"])


def get_provider_config(ai_config: dict[str, Any] | None) -> dict[str, Any]:
    ai_config = ai_config or {}
    integrations = ai_config.get("integrations", {})
    return {
        "provider": integrations.get("provider", "native"),
        "providers": integrations.get("providers", {}),
    }
