from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import asyncio
from datetime import datetime
import httpx
from fastapi import APIRouter, Request

from app.core.database import AsyncSessionLocal
from app.services.db_service import DBService
from app.integrations.vapi.prompts import render_system_prompt

logger = logging.getLogger("vapi_webhook")

# Base URL used when proxying Vapi server "tool-calls" to the existing
# FastAPI HTTP tool endpoints (appointments, payment link, etc.). By default
# we point to this same service on API_HOST/API_PORT, but you can override via
# INTERNAL_API_BASE_URL if you front this with a different hostname.
_INTERNAL_API_BASE_URL = os.getenv(
    "INTERNAL_API_BASE_URL",
    f"http://{os.getenv('API_HOST', '127.0.0.1')}:{int(os.getenv('API_PORT', 8000))}",
)


router = APIRouter()


@dataclass
class TenantConfig:
    """Minimal tenant configuration used to build system prompts.

    For now we keep this in-memory; later you can resolve this from your DB or
    a cache keyed by Vapi phoneNumberId / dialed number.
    """

    tenant_id: str
    business_name: str
    business_hours: str
    services: List[str]
    timezone: str = "Australia/Sydney"
    # Optional: if set, we return this assistantId directly to Vapi so it uses
    # the preconfigured dashboard assistant (including its tools) instead of
    # our transient assistant definition.
    assistant_id: Optional[str] = None


# TODO: replace these demo entries with real phoneNumberId / number mappings
TENANT_MAP: Dict[str, TenantConfig] = {
    # Original All Traders test number (if still in use)
    "9a078e9f-2225-4a67-a3f2-94cfb4db6adc": TenantConfig(
        tenant_id="tenant_all_traders",
        business_name="All Traders",
        business_hours="Mon–Fri 9am–5pm",
        services=["general enquiries", "bookings"],
        assistant_id=None,
    ),
    "+61468088108": TenantConfig(
        tenant_id="tenant_all_traders",
        business_name="All Traders",
        business_hours="Mon–Fri 9am–5pm",
        services=["general enquiries", "bookings"],
        assistant_id=None,
    ),

    # Nexa247 / Mark's Plumbing Services number using dynamic assistant-request
    # phoneNumberId from payload: abe13b19-cbed-404a-915b-a22ba818a3d3
    "abe13b19-cbed-404a-915b-a22ba818a3d3": TenantConfig(
        tenant_id="adf0c65d-02ca-4279-a741-8e7f7bb297ad",  # business_id to pass to all tools for this tenant
        business_name="Mark's Plumbing Services",
        business_hours="Mon–Fri 07:00–17:00, Sat 08:00–13:00",
        services=[
            "Emergency Plumbing",
            "Blocked Drains & Toilets",
            "Water Leaks & Pressure Issues",
            "Hot Water System Issues",
        ],
        assistant_id="38aeaea4-9222-417e-b027-348d79eeeb71",
    ),
    "+61255644466": TenantConfig(
        tenant_id="adf0c65d-02ca-4279-a741-8e7f7bb297ad",
        business_name="Mark's Plumbing Services",
        business_hours="Mon–Fri 07:00–17:00, Sat 08:00–13:00",
        services=[
            "Emergency Plumbing",
            "Blocked Drains & Toilets",
            "Water Leaks & Pressure Issues",
            "Hot Water System Issues",
        ],
        assistant_id="38aeaea4-9222-417e-b027-348d79eeeb71",
    ),
}


def _resolve_tenant_from_call_dict(call: Dict[str, Any]) -> TenantConfig:
    """Resolve tenant from the Vapi call object using phoneNumberId/number.

    This is intentionally lightweight: in-memory map + safe fallback.
    """

    phone_number_id: Optional[str] = call.get("phoneNumberId")
    phone_number_obj: Dict[str, Any] = call.get("phoneNumber") or {}
    dialed_number: Optional[str] = phone_number_obj.get("number")

    if phone_number_id and phone_number_id in TENANT_MAP:
        return TENANT_MAP[phone_number_id]
    if dialed_number and dialed_number in TENANT_MAP:
        return TENANT_MAP[dialed_number]

    # Safe default if we don't recognise the number yet
    return TenantConfig(
        tenant_id="unknown",
        business_name="our business",
        business_hours="Mon–Fri 9am–5pm",
        services=["general enquiries"],
    )




def _build_transient_assistant(tenant: TenantConfig) -> Dict[str, Any]:
    """Return a transient assistant for assistant-request.

    We only use this path when a tenant does not have a preconfigured
    dashboard assistant. For Nexa247/Mark's Plumbing we currently return an
    assistantId instead so Vapi uses the dashboard config and tools.
    """

    system_prompt = render_system_prompt(
        tenant_id=tenant.tenant_id,
        business_name=tenant.business_name,
        business_hours=tenant.business_hours,
        services=tenant.services,
        timezone=tenant.timezone,
    )

    assistant: Dict[str, Any] = {
        "firstMessage": f"Hi, thanks for calling {tenant.business_name}. How can I help you today?",
        "model": {
            "provider": os.getenv("VAPI_MODEL_PROVIDER", "openai"),
            "model": os.getenv("VAPI_MODEL", "gpt-4o"),
            "messages": [
                {"role": "system", "content": system_prompt},
            ],
        },
        # Vapi error logs list the allowed voiceIds for this org; pick one of
        # those (e.g. Kylie) as the default, but still allow env override.
        "voice": {
            "provider": os.getenv("VAPI_VOICE_PROVIDER", "vapi"),
            "voiceId": os.getenv("VAPI_VOICE_ID", "Kylie"),
        },
    }

    return assistant


def _parse_tool_arguments(arguments: Any) -> Dict[str, Any]:
    """Parse Vapi tool-call arguments which may be a dict or JSON string."""
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            return {"_raw": arguments}
    return {}


async def _execute_tool_via_http(name: str, args: Dict[str, Any]) -> Any:
    """Proxy Vapi server "tool-calls" to the existing FastAPI HTTP tool endpoints.

    This keeps Vapi-as-orchestrator thin: the actual booking / payment logic
    continues to live behind the `/appointments/*` and `/sms/payment-link`
    endpoints that were already part of the app before Vapi.
    """

    # Map tool names to relative HTTP endpoints
    tool_to_path = {
        "check_availability": "/appointments/check-availability",
        "book_appointment": "/appointments/book",
        "reschedule_appointment": "/appointments/reschedule",
        "cancel_appointment": "/appointments/cancel",
        "send_payment_link": "/sms/payment-link",
    }

    path = tool_to_path.get(name)
    if not path:
        return {"ok": False, "error": f"Unknown tool: {name}"}

    # Recreate a minimal Vapi-like envelope so the existing FastAPI endpoints
    # can keep using `_extract_tool_arguments` unchanged.
    payload = {
        "message": {
            "toolCallList": [
                {
                    "function": {
                        "name": name,
                        "arguments": args,
                    }
                }
            ]
        }
    }

    url = f"{_INTERNAL_API_BASE_URL}{path}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)

    # If the downstream endpoint failed, surface that back to Vapi clearly.
    if resp.status_code >= 400:
        return {
            "ok": False,
            "error": f"Upstream tool endpoint {path} returned {resp.status_code}: {resp.text}",
        }

    try:
        body = resp.json()
    except ValueError:
        return {
            "ok": False,
            "error": f"Upstream tool endpoint {path} returned non-JSON body",
        }

    # For now, just wrap the upstream response; the assistant can decide how
    # much of this to verbalise based on the tool schema.
    return {"ok": True, "upstream": body}


async def _persist_end_of_call(message: Dict[str, Any]) -> None:
    """Persist end-of-call details into the `calls` table via DBService.

    This runs best-effort in the background and should not raise into the
    webhook handler.
    """

    try:
        call = message.get("call") or {}
        if not call:
            return

        # Resolve tenant so we can attach business_id. Not all tenants use a
        # real UUID here (e.g. legacy 'tenant_all_traders'), so validate.
        tenant = _resolve_tenant_from_call_dict(call)
        business_id = None
        tenant_raw_id = tenant.tenant_id
        if tenant_raw_id and tenant_raw_id not in {"unknown"}:
            from uuid import UUID

            try:
                # Validate / normalize to a UUID string that matches DB schema
                business_id = str(UUID(tenant_raw_id))
            except Exception:
                business_id = None

        customer = call.get("customer") or {}
        caller_phone = customer.get("number") or customer.get("phoneNumber")

        call_sid = (
            call.get("twilioCallSid")
            or call.get("phoneCallProviderId")
            or call.get("id")
        )

        started_at = None
        ended_at = None
        started_raw = call.get("startedAt")
        ended_raw = call.get("endedAt")
        if started_raw:
            try:
                started_at = datetime.fromisoformat(started_raw.replace("Z", "+00:00"))
            except Exception:
                started_at = None
        if ended_raw:
            try:
                ended_at = datetime.fromisoformat(ended_raw.replace("Z", "+00:00"))
            except Exception:
                ended_at = None

        duration_seconds = call.get("durationSeconds")
        if duration_seconds is None and started_at and ended_at:
            duration_seconds = int((ended_at - started_at).total_seconds())

        report = message.get("report") or {}
        transcript = report.get("transcript")
        if not transcript:
            # Best-effort: flatten messages into a text transcript
            lines: List[str] = []
            for m in report.get("messages") or []:
                role = m.get("role") or ""
                content = m.get("content")
                if isinstance(content, list):
                    text = " ".join(seg.get("text", "") for seg in content if isinstance(seg, dict))
                else:
                    text = str(content or "")
                line = f"{role}: {text}".strip()
                if line:
                    lines.append(line)
            transcript = "\n".join(lines) if lines else None

        recording_url = call.get("recordingUrl") or report.get("recordingUrl")

        call_data: Dict[str, Any] = {
            "business_id": business_id,
            "call_sid": call_sid or "",
            "caller_phone": caller_phone or "",
            "started_at": started_at or datetime.utcnow(),
            "ended_at": ended_at,
            "duration_seconds": duration_seconds,
            "transcript": transcript,
            "intent": None,
            "outcome": None,
            "sentiment_score": None,
            "confidence_score": None,
            "recording_url": recording_url,
            "created_at": datetime.utcnow(),
        }

        async with AsyncSessionLocal() as session:
            db_service = DBService(session)
            await db_service.create_call(call_data)
    except Exception:
        logger.exception("Failed to persist end-of-call report")


@router.post("/")
async def vapi_root_webhook(request: Request):
    """Catch-all POST webhook endpoint for Vapi Server URL events.

    Lightweight version: handle assistant-request, tool-calls, and
    end-of-call-report here.
    """

    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        payload = {}

    message: Dict[str, Any] = payload.get("message") or {}
    msg_type: Optional[str] = message.get("type")

    # Previously printed the full payload for debugging; this is now disabled
    # to avoid excessive logging during production calls.
    # print("[VAPI WEBHOOK] Received on / with type=", msg_type, "payload=", payload)

    # Common call metadata (best-effort)
    call: Dict[str, Any] = message.get("call") or {}
    call_id: Optional[str] = call.get("id")

    # --- assistant-request -------------------------------------------------
    if msg_type == "assistant-request":
        if not call:
            raise RuntimeError("assistant-request missing call object")

        tenant = _resolve_tenant_from_call_dict(call)

        # If we have a preconfigured dashboard assistantId for this tenant,
        # tell Vapi to use that (including its tools configuration).
        if tenant.assistant_id:
            logger.info(
                "Handled assistant-request via assistantId",
                extra={"call_id": call_id, "tenant_id": tenant.tenant_id, "assistant_id": tenant.assistant_id},
            )
            return {"assistantId": tenant.assistant_id}

        # Fallback: build a transient assistant definition from our prompt
        assistant = _build_transient_assistant(tenant)

        logger.info(
            "Handled assistant-request via transient assistant",
            extra={"call_id": call_id, "tenant_id": tenant.tenant_id},
        )

        return {"assistant": assistant}

    # --- tool-calls -------------------------------------------------------
    if msg_type == "tool-calls":
        tool_calls: List[Dict[str, Any]] = message.get("toolCalls") or []
        results: List[Dict[str, Any]] = []

        for tc in tool_calls:
            name = tc.get("name")
            tool_call_id = tc.get("id")
            args = _parse_tool_arguments(tc.get("arguments"))

            try:
                result_payload = await _execute_tool_via_http(name, args)
            except Exception as ex:  # defensive: keep the call alive
                logger.exception("Tool execution failed", extra={"call_id": call_id, "tool": name})
                result_payload = {"ok": False, "error": str(ex)}

            results.append(
                {
                    "name": name,
                    "toolCallId": tool_call_id,
                    "result": json.dumps(result_payload) if not isinstance(result_payload, str) else result_payload,
                }
            )

        logger.info(
            "Handled tool-calls",
            extra={"call_id": call_id, "tool_count": len(results)},
        )
        return {"results": results}

    # --- end-of-call-report -----------------------------------------------
    if msg_type == "end-of-call-report":
        # Persist call summary best-effort in the background and return 200
        # quickly so we don't block Vapi.
        try:
            asyncio.create_task(_persist_end_of_call(message))
        except RuntimeError:
            # If no running loop (unlikely in FastAPI), fall back to inline
            await _persist_end_of_call(message)

        logger.info(
            "Received end-of-call-report",
            extra={"call_id": call_id},
        )
        return {"ok": True}

    # --- any other Vapi events -------------------------------------------
    logger.info("Received unsupported Vapi message type", extra={"type": msg_type, "call_id": call_id})
    return {"ok": True}
