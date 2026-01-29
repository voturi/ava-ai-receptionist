"""
Streaming AI Service for real-time LLM responses.

Uses OpenAI's streaming API to yield tokens as they're generated,
enabling low-latency text-to-speech synthesis.
"""

from __future__ import annotations

import os
from typing import Any, AsyncGenerator, Callable, Optional
import json
from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from app.services.intent_profiles import IssueIntentProfile

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from app.services.intent_detector import DetectedIntent


class StreamingAIService:
    """
    AI service with streaming token output.

    Designed for the streaming voice pipeline:
    STT transcript → LLM (streaming) → TTS (streaming)
    """

    def __init__(self):
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        # Use gpt-4o-mini for faster responses (good balance of speed/quality)
        self.model = "gpt-4o-mini"

    def get_system_prompt(
        self,
        business_name: str = "our business",
        business_config: Optional[dict] = None,
        conversation_mode: Optional[str] = None,
        issue_profile: Optional[IssueIntentProfile] = None,
    ) -> str:
        """
        System prompt optimized for voice conversations.

        Key differences from text-based prompts:
        - Shorter responses (voice needs to be concise)
        - Natural speech patterns
        - No markdown or formatting
        """
        if business_config is None:
            business_config = {}

        ai_config = business_config.get("ai_config") or {}
        industry = business_config.get("industry") or "business"
        services = business_config.get("services") or []
        working_hours = business_config.get("working_hours") or {}

        # Conversation mode: guides how aggressively to push into booking.
        # - "booking": caller has clearly asked to book/schedule.
        # - "emergency_info": caller likely has an urgent issue; prioritise
        #   safety and rapid dispatch over general chit-chat.
        # - anything else / None: information & triage mode.
        if conversation_mode == "booking":
            mode_block = (
                "CONVERSATION MODE (BOOKING):\n"
                "- The caller has explicitly indicated they want to book, schedule, or reserve an appointment.\n"
                "- You SHOULD guide them through the booking flow and collect all mandatory fields.\n"
                "- Still answer any direct questions clearly before continuing the booking steps.\n"
            )
        elif conversation_mode == "emergency_info":
            mode_block = (
                "CONVERSATION MODE (EMERGENCY):\n"
                "- The caller appears to have an urgent or emergency issue.\n"
                "- FIRST, check safety and whether they can safely turn off water or gas.\n"
                "- Collect the address and a short description of the emergency before anything else.\n"
                "- Keep responses calm, direct, and focused on dispatching urgent help.\n"
            )
        else:
            mode_block = (
                "CONVERSATION MODE (INFO / TRIAGE):\n"
                "- The caller has NOT clearly asked to book or schedule yet.\n"
                "- DO NOT start the booking flow or ask for address, preferred day/time, name, or mobile number unless the caller clearly says they want to book, schedule, reserve, or make an appointment.\n"
                "- Focus on understanding the issue and answering questions. After you answer, you may politely ask once if they would like to book a time.\n"
            )

        tone = ai_config.get("tone", "warm, friendly, and professional")
        language = ai_config.get("language", "en-AU")

        services_summary = ", ".join(
            service.get("name", str(service)) if isinstance(service, dict) else str(service)
            for service in services[:8]
        )
        if not services_summary:
            services_summary = "Ask if the caller needs a service."

        working_hours_summary = ", ".join(
            f"{day}: {hours}" for day, hours in list(working_hours.items())[:7]
        )
        if not working_hours_summary:
            working_hours_summary = "Ask if the caller needs business hours."

        policies_summary = business_config.get("policies_summary") or "Not provided."
        faqs_summary = business_config.get("faqs_summary") or "Not provided."

        issue_block = ""
        if issue_profile is not None:
            cq_snippet = " ".join(issue_profile.clarifying_questions[:3]) if issue_profile.clarifying_questions else ""
            jobs_summary = ", ".join(issue_profile.jobs_covered[:5]) if issue_profile.jobs_covered else "Not specified."
            issue_block = (
                "CURRENT CALL INTENT:\n"
                f"- Workflow: {issue_profile.workflow}\n"
                f"- Purpose: {issue_profile.purpose or 'Not specified.'}\n"
                f"- Customer intent: {issue_profile.customer_intent or 'Not specified.'}\n"
                f"- Typical jobs: {jobs_summary}\n"
                "\nWhen speaking with the caller:\n"
                f"- Treat this as a {issue_profile.workflow.lower()} scenario.\n"
                "- Use the saved clarifying questions to quickly understand the job.\n"
                f"- Example clarifying questions: {cq_snippet}\n"
                f"- Follow this routing logic when positioning the job: {issue_profile.routing_logic or 'standard plumbing routing.'}\n"
            )

        return f"""You are Echo, the AI receptionist for {business_name} ({industry}).
Tone: {tone}. Language: {language}. Be warm and concise (1-2 sentences).

BUSINESS CONTEXT:
- Services: {services_summary}
- Hours: {working_hours_summary}
- Policies: {policies_summary}
- FAQs: {faqs_summary}

{mode_block}

{issue_block}

TOOLS POLICY:
- Use tools only for booking lookups when explicitly asked.
- Booking lookups use caller phone (do not request business_id).

TRADIES BEHAVIOR:
- If urgent issue (burst pipe, flooding, gas smell, no power), ask for address + safety step, then offer urgent dispatch.
- Ask for job details: issue type, address/suburb, access notes, preferred time window.
- Keep responses short and reassuring.

BOOKING FLOW (mandatory fields when the caller clearly wants to book):
1. Service needed
2. Preferred day
3. Preferred time
4. Customer name
5. Customer mobile number (required for confirmation)
6. Confirm all details before finalizing

When in booking mode, collect the mobile number before confirming a booking.
Only begin collecting booking fields after the caller clearly indicates they want to book, schedule, reserve, or make an appointment.
Once all details are collected, ask for explicit permission to finalize the booking (e.g., "Shall I go ahead and finalise that?") and wait for a yes.

VOICE CONVERSATION RULES:
- Use Australian expressions: "no worries", "lovely", "arvo"
- Keep responses SHORT: 1-2 sentences, 15-25 words max
- Sound natural and warm, like a friendly human
- Never use bullet points, lists, or formatted text
- Don't say "I'm an AI" - just be helpful
- Do NOT say goodbye unless the booking is confirmed or the request is fully resolved
- Avoid farewell language before confirmation; keep the conversation open-ended
- Do NOT claim a booking is confirmed; say you'll confirm once details are collected

If unsure about anything, say "Let me check on that for you" and keep it brief."""

    async def get_streaming_response(
        self,
        user_message: str,
        conversation_history: Optional[list] = None,
        business_name: str = "our business",
        conversation_mode: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream AI response token by token.

        Yields text chunks as they're generated by the LLM.
        Perfect for piping directly to streaming TTS.

        Usage:
            async for chunk in ai.get_streaming_response("Hello"):
                await tts.send_text(chunk)
            await tts.flush()
        """
        if conversation_history is None:
            conversation_history = []

        messages = [
            {
                "role": "system",
                "content": self.get_system_prompt(
                    business_name,
                    business_config=None,
                    conversation_mode=conversation_mode,
                    issue_profile=None,
                ),
            },
            *conversation_history,
            {"role": "user", "content": user_message},
        ]

        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=100,  # Keep responses short for voice
                temperature=0.7,
                stream=True,
            )

            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content

        except Exception as e:
            print(f"❌ OpenAI Streaming Error: {e}")
            # Yield a fallback message
            yield "Sorry, I'm having trouble right now. Can you try again?"

    async def get_response_with_buffer(
        self,
        user_message: str,
        conversation_history: Optional[list] = None,
        business_name: str = "our business",
        min_chunk_size: int = 10,
        conversation_mode: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream AI response with buffering for natural speech breaks.

        Buffers tokens until we hit a natural break point (punctuation)
        or reach min_chunk_size. This produces better TTS output.

        Args:
            user_message: The user's input
            conversation_history: Previous messages
            business_name: Business name for personalization
            min_chunk_size: Minimum characters before yielding on punctuation
        """
        buffer = ""

        async for token in self.get_streaming_response(
            user_message,
            conversation_history,
            business_name,
            conversation_mode,
        ):
            buffer += token

            # Check for natural break points
            if self._should_yield(buffer, min_chunk_size):
                yield buffer
                buffer = ""

        # Yield any remaining text
        if buffer:
            yield buffer

    def _should_yield(self, buffer: str, min_size: int) -> bool:
        """
        Determine if we should yield the buffer to TTS.

        Yields on:
        - Sentence endings (. ! ?)
        - Clause breaks (, ; :) if buffer is long enough
        - Buffer exceeds max size (50 chars)
        """
        if not buffer:
            return False

        stripped = buffer.rstrip()

        # Always yield on sentence end
        if stripped.endswith((".", "!", "?")):
            return len(buffer) >= min_size

        # Yield on clause breaks if buffer is decent size
        if stripped.endswith((",", ";", ":")):
            return len(buffer) >= min_size

        # Yield if buffer is getting too long
        return len(buffer) >= 50

    async def classify_service(
        self,
        *,
        user_utterances: list[str],
        services: list[Any],
        business_name: str = "our business",
        industry: Optional[str] = None,
    ) -> Optional[str]:
        """Classify a customer's issue description into one configured service.

        This is a lightweight, non-streaming helper used when heuristic
        string-matching cannot confidently map the user's natural language
        description (e.g. "leaking bathroom pipe and non-working flush")
        to one of the configured services.

        Returns the chosen service *name* (as configured on the business)
        or None if a confident mapping cannot be made.
        """
        if not services or not user_utterances:
            return None

        # Normalise services into display names + optional descriptions
        formatted_services: list[tuple[str, str]] = []
        for service in services:
            if isinstance(service, dict):
                name = str(service.get("name") or "").strip()
                desc = str(
                    service.get("description")
                    or service.get("details")
                    or service.get("notes")
                    or ""
                ).strip()
            else:
                name = str(service).strip()
                desc = ""
            if not name:
                continue
            formatted_services.append((name, desc))

        if not formatted_services:
            return None

        services_block = "\n".join(
            f'- "{name}" - {desc}' if desc else f'- "{name}"'
            for name, desc in formatted_services[:20]
        )

        # Use the last few user utterances as the issue description context
        non_empty_utterances = [u.strip() for u in user_utterances if u and u.strip()]
        if not non_empty_utterances:
            return None

        recent_snippet = "\n".join(
            f"Customer: {utt}" for utt in non_empty_utterances[-3:]
        )

        system_prompt = (
            "You are a classifier that maps a customer's plumbing or trade "
            "issue description to exactly ONE of the business's configured "
            "services.\n\n"
            "Rules:\n"
            "- Only choose from the provided services list.\n"
            "- If more than one could fit, choose the *most* specific match.\n"
            "- If none are appropriate, respond with null.\n"
            "- Respond with STRICT JSON only, no explanation."
        )

        user_prompt = (
            f"Business: {business_name} ({industry or 'business'})\n\n"
            f"Available services:\n{services_block}\n\n"
            f"Recent customer conversation:\n{recent_snippet}\n\n"
            "Based on this, choose the single best matching service from the "
            "list. If none apply, use null."
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                max_tokens=64,
            )

            content = response.choices[0].message.content or ""
            content = content.strip()

            # Best effort: tolerate minor deviations like surrounding text,
            # including Markdown code fences (```json ... ```), bare strings,
            # or full JSON objects.
            def _strip_code_fences(text: str) -> str:
                if text.startswith("```") and text.endswith("```"):
                    # Remove leading ```lang (if present) and trailing ```
                    inner = text.strip("`")  # quick fallback
                    # More robust: strip first line starting with ``` and last ``` line
                    lines = text.splitlines()
                    if lines and lines[0].lstrip().startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip().startswith("```"):
                        lines = lines[:-1]
                    return "\n".join(lines).strip()
                return text

            raw = _strip_code_fences(content)

            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                # Try to extract the first JSON object from the string
                start = raw.find("{")
                end = raw.rfind("}")
                if start != -1 and end != -1 and end > start:
                    try:
                        parsed = json.loads(raw[start : end + 1])
                    except json.JSONDecodeError:
                        print(f"⚠️ Could not parse service classification JSON: {raw}")
                        return None
                else:
                    # As a fallback, treat the stripped text as a raw name
                    # string (e.g. "Water Leaks & Pressure Issues").
                    stripped = raw.strip().strip("` ")
                    if stripped:
                        parsed = stripped
                    else:
                        print(f"⚠️ Unexpected service classification response: {content}")
                        return None

            # If the model returns bare null or a non-object (e.g. "null"),
            # treat that as "no mapping" rather than raising.
            if not isinstance(parsed, dict):
                if parsed is None:
                    return None
                # If it's a raw string, we can try to interpret it as a
                # service name directly; otherwise, give up safely.
                if isinstance(parsed, str):
                    raw_name_str = parsed.strip().lower()
                    if not raw_name_str:
                        return None
                    for name, _ in formatted_services:
                        if name.lower() == raw_name_str:
                            return name
                    for name, _ in formatted_services:
                        if raw_name_str in name.lower() or name.lower() in raw_name_str:
                            return name
                    print(f"⚠️ Service classification returned unknown raw string: {parsed}")
                    return None
                print(f"⚠️ Service classification returned non-object JSON: {parsed}")
                return None

            raw_name = parsed.get("service_name")
            if not raw_name:
                return None

            raw_name_str = str(raw_name).strip().lower()
            if not raw_name_str:
                return None

            # Map back to the exact configured name (case-insensitive match)
            for name, _ in formatted_services:
                if name.lower() == raw_name_str:
                    return name

            # If the model returned something close but not exact, fall
            # back to a more permissive contains match as a last resort.
            for name, _ in formatted_services:
                if raw_name_str in name.lower() or name.lower() in raw_name_str:
                    return name

            print(
                f"⚠️ Service classification returned unknown name: {raw_name} from {content}"
            )
            return None

        except Exception as e:  # pragma: no cover - defensive logging
            print(f"❌ Service classification error: {e}")
            return None

    async def stream_with_tools(
        self,
        user_message: str,
        conversation_history: Optional[list] = None,
        business_profile: Optional[dict] = None,
        tools: Optional[list] = None,
        tool_executor: Optional[Callable[[str, dict], Any]] = None,
        max_tool_calls: int = 2,
        prefetched_tools: Optional[list[dict]] = None,
        conversation_mode: Optional[str] = None,
        intent: Optional["DetectedIntent"] = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Stream a response with tool calling.

        Yields events:
        - {"type": "content", "text": "..."}
        - {"type": "tool_call", "name": "...", "arguments": {...}}
        """
        if conversation_history is None:
            conversation_history = []

        # If an upstream intent detector has mapped this utterance to a
        # domain-specific issue, pass that profile into the system prompt so
        # the LLM can specialise its behaviour.
        issue_profile: Optional[IssueIntentProfile] = None
        if intent is not None:
            issue_profile = getattr(intent, "issue_profile", None)

        system_prompt = self.get_system_prompt(
            business_name=(business_profile or {}).get("business_name", "our business"),
            business_config=business_profile or {},
            conversation_mode=conversation_mode,
            issue_profile=issue_profile,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            *conversation_history,
            {"role": "user", "content": user_message},
        ]
        if prefetched_tools:
            for idx, tool in enumerate(prefetched_tools, start=1):
                tool_call_id = f"prefetch_{idx}"
                messages.append({
                    "role": "assistant",
                    "tool_calls": [{
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "arguments": json.dumps(tool.get("arguments", {})),
                        },
                    }],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps(tool.get("result", {})),
                })

        tool_calls_used = 0
        tool_definitions = tools or []

        while True:
            tool_call_name = None
            tool_call_id = None
            tool_args_json = ""

            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=150,
                temperature=0.7,
                stream=True,
                tools=tool_definitions or None,
                tool_choice="auto",
            )

            async for chunk in stream:
                delta = chunk.choices[0].delta

                if getattr(delta, "tool_calls", None):
                    for call in delta.tool_calls:
                        if call.id:
                            tool_call_id = call.id
                        if call.function and call.function.name:
                            tool_call_name = call.function.name
                        if call.function and call.function.arguments:
                            tool_args_json += call.function.arguments
                    continue

                if delta.content:
                    if tool_call_name:
                        continue
                    yield {"type": "content", "text": delta.content}

            if tool_call_name:
                tool_calls_used += 1
                if tool_calls_used > max_tool_calls or not tool_executor:
                    yield {
                        "type": "content",
                        "text": "I'm having trouble pulling that up right now. Would you like me to take a message?",
                    }
                    break

                try:
                    tool_args = json.loads(tool_args_json or "{}")
                except json.JSONDecodeError:
                    tool_args = {}

                missing_info = self._validate_tool_args(tool_call_name, tool_args)
                if missing_info:
                    yield {"type": "content", "text": missing_info}
                    break

                yield {"type": "tool_call", "name": tool_call_name, "arguments": tool_args}

                tool_result = await tool_executor(tool_call_name, tool_args)

                tool_call_id = tool_call_id or f"tool_call_{tool_calls_used}"
                messages.append({
                    "role": "assistant",
                    "tool_calls": [{
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": tool_call_name,
                            "arguments": json.dumps(tool_args),
                        },
                    }],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps(tool_result),
                })
                continue

            break

    def _validate_tool_args(self, tool_name: str, tool_args: dict) -> Optional[str]:
        """Validate tool args and return a user prompt if required fields are missing.

        Note: For tools like ``get_latest_booking`` we deliberately avoid
        prompting for a mobile number here. The ToolRouter already falls
        back to the caller's phone when ``customer_phone`` is omitted, so
        asking the user again would be redundant and confusing.
        """
        if tool_name in {"get_policies", "get_faqs"}:
            if not tool_args.get("topic"):
                return "Which topic should I check? For example: cancellation, pricing, or parking."
        if tool_name == "get_booking_by_id" and not tool_args.get("booking_id"):
            return "Do you have the booking ID?"
        # get_latest_booking: no explicit validation here; caller_phone is used implicitly.
        return None


# Singleton instance
streaming_ai_service = StreamingAIService()
