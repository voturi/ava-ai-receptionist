Ideas is  *not* encode “all services + all use cases” into prompts.
but to  design an **intent routing system**, and only load what is relevant.

Think in terms of a *dispatcher architecture*, not a prompt architecture.

 AI receptionist should behave like:

1. Detect intent
2. Select service(s)
3. Load only those service instructions
4. Execute
5. Unload everything else

This is how you scale to 50 services without destroying your context window.

---

Conceptually, split your system into four layers:

```
[ System Prompt (identity + tone) ]
          ↓
[ Intent Classifier ]
          ↓
[ Service Router ]
          ↓
[ Service-Specific Prompts ]
```

---

1. Intent detection first (always lightweight)

Your first step should be a small classification pass:

Example:

```json
{
  "intent": "book_appointment",
  "services": ["plumbing", "gas_fitting"],
  "confidence": 0.92
}
```

This prompt is tiny and fast:

```
Classify the caller's intent and which business services it relates to.
Return JSON only.
```

This costs very few tokens and keeps the core model clean.

---

2. Services are modular, not global

Each service has its own prompt block:

```
/services
  /plumbing.md
  /electrical.md
  /hvac.md
  /salon_booking.md
  /restaurant_reservation.md
```

Each contains:

* What that service does
* What questions to ask
* What data is required
* What tools can be called
* What mistakes to avoid

You only load the ones that match the detected intent.

---

3. Multi-service intent handling

Real users often say things like:

> “My hot water isn’t working and I smell gas.”

That hits:

* plumbing
* gas fitting
* emergency handling

Your router does:

```json
{
  "services": ["emergency", "plumbing", "gas_fitting"],
  "priority": ["emergency", "gas_fitting", "plumbing"]
}
```

Then you inject prompts in order:

1. Emergency policy
2. Gas safety protocol
3. Plumbing service workflow

Everything else stays out of memory.

---

4. Service prompts should be procedural, not verbose

Bad service prompt:

> Long explanations, full policies, marketing fluff.

Good service prompt:

```
Service: Plumbing
When activated:
- Confirm urgency
- Ask for location
- Ask for problem type
- Offer emergency dispatch if applicable
- Collect availability
- Call booking tool
Never:
- Diagnose
- Provide repair advice
```

Short, executable instructions.

---

5. Context window becomes predictable

Your total token load becomes:

| Layer               | Tokens   |
| ------------------- | -------- |
| System prompt       | 200      |
| Intent prompt       | 150      |
| 1–3 service prompts | 300–900  |
| Conversation        | Variable |
| Tools               | Small    |

You stay under 2–3k tokens even for complex interactions.

Which is production-safe.

---

6. Your receptionist becomes a workflow engine

Not a chatbot.

It behaves like:

```
Caller speaks
   ↓
Intent Classifier
   ↓
Service Router
   ↓
Load Service Instructions
   ↓
Collect Data
   ↓
Execute Tools
   ↓
Confirm Resolution
```

This is how enterprise call centers work, just AI-driven.

---

7. Why this matters for your product

For your AI receptionist startup, this gives you:

* Infinite scalability of services
* Simple onboarding of new industries
* Clear debugging (“intent wrong” vs “service wrong”)
* Faster responses
* Lower cost
* Cleaner logs
* Easier compliance

And most importantly:

> You are building an **AI operating system**, not a prompt.

Prompts are just modules inside it.
