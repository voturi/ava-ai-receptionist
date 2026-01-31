"""
Production-grade FastAPI handler for Vapi Server URL events, including:
- assistant-request (returns transient assistant with tenant-specific prompt)
- tool-calls (executes tools and returns results)
- end-of-call-report (queues DB work / logging)

Design goals:
- <200ms typical for assistant-request (cache first, minimal IO)
- defensive parsing + Pydantic models
- structured logging + correlation ids
- optional request signature verification (HMAC)
- pluggable tenant resolver (in-memory + Redis optional)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

# -----------------------------------------------------------------------------
# Logging (structured-ish)
# -----------------------------------------------------------------------------

logger = logging.getLogger("vapi_webhook")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

VAPI_WEBHOOK_SECRET = os.getenv("VAPI_WEBHOOK_SECRET", "")  # set if you want signature verification
ASSISTANT_MODEL = os.getenv("VAPI_MODEL", "gpt-4o")         # set to your preferred model
MODEL_PROVIDER = os.getenv("VAPI_MODEL_PROVIDER", "openai")
DEFAULT_VOICE_PROVIDER = os.getenv("VAPI_VOICE_PROVIDER", "deepgram")
DEFAULT_VOICE_ID = os.getenv("VAPI_VOICE_ID", "australian_male")
TENANT_CACHE_TTL_S = int(os.getenv("TENANT_CACHE_TTL_S", "300"))  # 5 min
ASSISTANT_REQUEST_BUDGET_MS = int(os.getenv("ASSISTANT_REQUEST_BUDGET_MS", "6500"))

# -----------------------------------------------------------------------------
# Pydantic models for the Vapi webhook envelope
# -----------------------------------------------------------------------------

class PhoneNumber(BaseModel):
    number: Optional[str] = None
    name: Optional[str] = None


class Customer(BaseModel):
    number: Optional[str] = None


class Call(BaseModel):
    id: str
    status: Optional[str] = None
    phoneNumberId: Optional[str] = None
    phoneNumber: Optional[PhoneNumber] = None
    customer: Optional[Customer] = None
    startedAt: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ToolCall(BaseModel):
    # Vapi tool-calls typically include these fields
    id: str
    name: str
    arguments: Union[str, Dict[str, Any]]


class MessageBase(BaseModel):
    type: str
    call: Optional[Call] = None


class AssistantRequestMessage(MessageBase):
    type: Literal["assistant-request"]


class ToolCallsMessage(MessageBase):
    type: Literal["tool-calls"]
    toolCalls: List[ToolCall] = Field(default_factory=list)


class EndOfCallReportMessage(MessageBase):
    type: Literal["end-of-call-report"]
    # Vapi sends a lot here; keep it flexible
    # You can add fields as you need: transcript, summary, etc.
    report: Optional[Dict[str, Any]] = None


VapiMessage = Union[AssistantRequestMessage, ToolCallsMessage, EndOfCallReportMessage]


class WebhookEnvelope(BaseModel):
    message: Dict[str, Any]


# -----------------------------------------------------------------------------
# Tenant model + caching
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class TenantConfig:
    tenant_id: str
    business_name: str
    business_hours: str
    services: List[str]
    timezone: str = "Australia/Sydney"
    # Add more: address, policies, booking link, disclaimers, pricing, etc.


class TTLCache:
    """Tiny in-memory TTL cache for low-latency assistant-request path."""
    def __init__(self, ttl_s: int):
        self.ttl_s = ttl_s
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        now = time.time()
        async with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            exp, value = item
            if exp < now:
                self._store.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: Any) -> None:
        exp = time.time() + self.ttl_s
        async with self._lock:
            self._store[key] = (exp, value)


tenant_cache = TTLCache(ttl_s=TENANT_CACHE_TTL_S)

# -----------------------------------------------------------------------------
# Signature verification (optional)
# -----------------------------------------------------------------------------

def verify_signature(secret: str, body: bytes, signature_header: Optional[str]) -> None:
    """
    Generic HMAC verification. Exact header name/format may differ depending on your Vapi setup.
    If you do not have a signature mechanism enabled, keep VAPI_WEBHOOK_SECRET empty and skip.

    Expected header format in this example: "sha256=<hex>"
    """
    if not secret:
        return  # verification disabled

    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing signature")

    try:
        scheme, sig_hex = signature_header.split("=", 1)
        if scheme.lower() != "sha256":
            raise ValueError("Unsupported signature scheme")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid signature header format")

    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, sig_hex):
        raise HTTPException(status_code=401, detail="Invalid signature")


# -----------------------------------------------------------------------------
# Tenant resolution (plug in your real logic)
# -----------------------------------------------------------------------------

async def resolve_tenant_from_call(call: Call) -> TenantConfig:
    """
    Resolve tenant using phoneNumberId (best) or fallback to E.164 dialed number.
    MUST be fast; avoid hitting the primary DB on cold path.
    Use cache + Redis (optional) + preloaded mappings.
    """
    # 1) Choose a stable tenant key
    tenant_key = call.phoneNumberId or (call.phoneNumber.number if call.phoneNumber else None)
    if not tenant_key:
        # Unknown routing -> safe default (generic tenant)
        return TenantConfig(
            tenant_id="unknown",
            business_name="our business",
            business_hours="Mon–Fri 9am–5pm",
            services=["general enquiries"],
        )

    # 2) Check in-memory cache
    cached = await tenant_cache.get(tenant_key)
    if cached:
        return cached

    # 3) TODO: Optional Redis cache here (recommended for multi-worker deployments)
    # Example (pseudo):
    # tenant_json = await redis.get(f"tenant:{tenant_key}")
    # if tenant_json: parse -> set in mem -> return

    # 4) Fallback mapping (replace with your datastore)
    # In production, you'd maintain a mapping table:
    # vapi_phone_number_id -> tenant_id + config snapshot
    # and keep it warmed (preload into Redis).
    demo_map: Dict[str, TenantConfig] = {
        "pn_2f8c9d1a4b5e": TenantConfig(
            tenant_id="tenant_acme",
            business_name="Acme Plumbing",
            business_hours="Mon–Fri 7am–5pm, Sat 8am–12pm",
            services=[
                "Emergency plumbing",
                "Blocked drains",
                "Hot water repairs",
                "Gas fitting",
                "Leak detection",
            ],
        )
    }

    tenant = demo_map.get(tenant_key)
    if not tenant:
        tenant = TenantConfig(
            tenant_id="unknown",
            business_name="our business",
            business_hours="Mon–Fri 9am–5pm",
            services=["general enquiries"],
        )

    await tenant_cache.set(tenant_key, tenant)
    return tenant


# -----------------------------------------------------------------------------
# Prompt construction
# -----------------------------------------------------------------------------

def build_system_prompt(tenant: TenantConfig) -> str:
    services_str = ", ".join(tenant.services[:12])
    return (
        f"You are the AI voice receptionist for {tenant.business_name}.\n"
        f"Timezone: {tenant.timezone}.\n"
        f"Business hours: {tenant.business_hours}.\n"
        f"Services: {services_str}.\n\n"
        "Goals:\n"
        "1) Answer questions succinctly.\n"
        "2) Qualify the request (service type, urgency, suburb, preferred time).\n"
        "3) If caller wants to book: collect details and call the booking tool.\n"
        "4) If uncertain: take a message and confirm callback number.\n\n"
        "Safety/Policy:\n"
        "- Do not invent prices.\n"
        "- If caller reports gas smell, advise immediate safety steps and escalation.\n"
    )


def build_transient_assistant(tenant: TenantConfig) -> Dict[str, Any]:
    """
    Return a transient assistant object for the assistant-request response.
    Keep it lean: avoid huge tool schemas; only what you need.
    """
    system_prompt = build_system_prompt(tenant)

    # Example tool definition (match your existing tool-calls contract)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "create_lead",
                "description": "Create or update a lead in the CRM/DB.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string"},
                        "urgency": {"type": "string", "enum": ["emergency", "today", "this_week", "quote"]},
                        "suburb": {"type": "string"},
                        "preferred_time": {"type": "string"},
                        "notes": {"type": "string"},
                        "caller_number": {"type": "string"},
                        "tenant_id": {"type": "string"},
                    },
                    "required": ["service", "tenant_id"]
                }
            }
        }
    ]

    return {
        "firstMessage": f"Hi, thanks for calling {tenant.business_name}. How can I help you today?",
        "model": {
            "provider": MODEL_PROVIDER,
            "model": ASSISTANT_MODEL,
            "messages": [{"role": "system", "content": system_prompt}],
        },
        "voice": {"provider": DEFAULT_VOICE_PROVIDER, "voiceId": DEFAULT_VOICE_ID},
        "tools": tools,
        # Optional: add "metadata" if your downstream uses it
        "metadata": {"tenant_id": tenant.tenant_id, "business_name": tenant.business_name},
    }


# -----------------------------------------------------------------------------
# Tool execution (your real tools go here)
# -----------------------------------------------------------------------------

async def execute_tool(name: str, args: Dict[str, Any], call: Optional[Call]) -> Any:
    """
    Execute a tool call. Keep it reliable and fast.
    If you do DB ops, do them async and with timeouts/retries.
    """
    if name == "create_lead":
        # Example: validate tenant_id exists, write to DB, return lead id.
        # Replace with your own DB layer.
        lead_id = f"lead_{int(time.time())}"
        return {"ok": True, "lead_id": lead_id}

    # Unknown tool -> return an error payload (do not raise; keep model moving)
    return {"ok": False, "error": f"Unknown tool: {name}"}


def parse_tool_arguments(tool_call: ToolCall) -> Dict[str, Any]:
    if isinstance(tool_call.arguments, dict):
        return tool_call.arguments
    if isinstance(tool_call.arguments, str):
        try:
            return json.loads(tool_call.arguments)
        except json.JSONDecodeError:
            return {"_raw": tool_call.arguments}
    return {}


# -----------------------------------------------------------------------------
# FastAPI app + handler
# -----------------------------------------------------------------------------

app = FastAPI()


@app.post("/vapi/webhook")
async def vapi_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_vapi_signature: Optional[str] = Header(default=None),  # adjust header name to your actual setup
) -> Response:
    start = time.perf_counter()

    body = await request.body()

    # Optional signature verification
    verify_signature(VAPI_WEBHOOK_SECRET, body, x_vapi_signature)

    try:
        env = WebhookEnvelope.model_validate_json(body)
    except ValidationError as e:
        logger.warning("Invalid envelope", extra={"error": str(e)})
        raise HTTPException(status_code=400, detail="Invalid payload envelope")

    msg_dict = env.message
    msg_type = msg_dict.get("type")

    # Correlation fields (best effort)
    call_id = (msg_dict.get("call") or {}).get("id")
    phone_number_id = (msg_dict.get("call") or {}).get("phoneNumberId")

    # --- assistant-request ---
    if msg_type == "assistant-request":
        try:
            msg = AssistantRequestMessage.model_validate(msg_dict)
        except ValidationError as e:
            logger.warning("Invalid assistant-request", extra={"call_id": call_id, "error": str(e)})
            raise HTTPException(status_code=400, detail="Invalid assistant-request")

        if not msg.call:
            raise HTTPException(status_code=400, detail="Missing call info")

        # Enforce time budget defensively
        elapsed_ms = (time.perf_counter() - start) * 1000
        remaining_ms = ASSISTANT_REQUEST_BUDGET_MS - int(elapsed_ms)
        if remaining_ms <= 0:
            # If we're already out of budget, return safe generic assistant quickly
            tenant = TenantConfig(
                tenant_id="unknown",
                business_name="our business",
                business_hours="Mon–Fri 9am–5pm",
                services=["general enquiries"],
            )
        else:
            tenant = await resolve_tenant_from_call(msg.call)

        assistant = build_transient_assistant(tenant)

        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "assistant-request handled",
            extra={
                "call_id": msg.call.id,
                "phoneNumberId": msg.call.phoneNumberId,
                "tenant_id": tenant.tenant_id,
                "duration_ms": duration_ms,
            },
        )

        return JSONResponse(content={"assistant": assistant})

    # --- tool-calls ---
    if msg_type == "tool-calls":
        try:
            msg = ToolCallsMessage.model_validate(msg_dict)
        except ValidationError as e:
            logger.warning("Invalid tool-calls", extra={"call_id": call_id, "error": str(e)})
            raise HTTPException(status_code=400, detail="Invalid tool-calls")

        results = []
        for tc in msg.toolCalls:
            args = parse_tool_arguments(tc)
            try:
                result = await execute_tool(tc.name, args, msg.call)
            except Exception as ex:
                logger.exception("Tool execution failed", extra={"call_id": call_id, "tool": tc.name})
                result = {"ok": False, "error": str(ex)}

            # Vapi expects results with name + toolCallId + result
            results.append(
                {
                    "name": tc.name,
                    "toolCallId": tc.id,
                    "result": json.dumps(result) if not isinstance(result, str) else result,
                }
            )

        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "tool-calls handled",
            extra={"call_id": call_id, "phoneNumberId": phone_number_id, "tool_count": len(results), "duration_ms": duration_ms},
        )
        return JSONResponse(content={"results": results})

    # --- end-of-call-report ---
    if msg_type == "end-of-call-report":
        try:
            msg = EndOfCallReportMessage.model_validate(msg_dict)
        except ValidationError as e:
            logger.warning("Invalid end-of-call-report", extra={"call_id": call_id, "error": str(e)})
            raise HTTPException(status_code=400, detail="Invalid end-of-call-report")

        # Do NOT block the webhook on DB writes; enqueue background work
        background_tasks.add_task(handle_end_of_call_report, msg_dict)

        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "end-of-call-report accepted",
            extra={"call_id": call_id, "phoneNumberId": phone_number_id, "duration_ms": duration_ms},
        )
        return Response(status_code=200)

    # --- unknown message types ---
    logger.info("Unknown message type", extra={"type": msg_type, "call_id": call_id})
    return Response(status_code=200)


async def handle_end_of_call_report(payload: Dict[str, Any]) -> None:
    """
    Background DB ops / analytics / billing reconciliation.
    Keep it resilient: timeouts, retries, idempotency (by call.id).
    """
    try:
        call = payload.get("call") or {}
        call_id = call.get("id")
        tenant_id = None

        # If you used assistant.metadata above, you can often recover it in reports
        # depending on how you store call context. Keep it flexible.
        report = payload.get("report") or {}
        # Example: persist transcript, summary, latency metrics, etc.
        # Replace with your DB writes.
        logger.info("Persisting end-of-call report", extra={"call_id": call_id, "tenant_id": tenant_id})
        await asyncio.sleep(0)  # placeholder
    except Exception:
        logger.exception("Failed to process end-of-call-report")


# -----------------------------------------------------------------------------
# Health check
# -----------------------------------------------------------------------------

@app.get("/healthz")
async def healthz() -> Dict[str, str]:
    return {"status": "ok"}