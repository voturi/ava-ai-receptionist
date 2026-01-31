### **You** (30/01/2026, 11:19:07)

Walk me through building an agent

---

### **Assistant** (30/01/2026, 11:19:09)

I'd be happy to walk you through building a voice AI agent! Let me ask you a few questions to make sure I build exactly what you need.

**What would you like your agent to do?**

For example:
- Answer customer support questions
- Book appointments
- Qualify sales leads
- Take orders
- Something else entirely?

---

### **You** (30/01/2026, 11:20:39)

AI receptionsist assistant for all traders . With check availablity ( calendar, calendy), book appointments, re-schedule appointments, cancel appoints, send SMS with a link for payment etc. I have a fast api backend for DB integration

---

### **Assistant** (30/01/2026, 11:20:42)

Great, this is a solid use case! Let me gather a few more details.

**What would you like your agent to sound like?**

For example:
- Professional and formal
- Friendly and conversational
- Warm and empathetic
- Energetic and upbeat

Also, do you have a preference for voice gender or accent?

---

### **You** (30/01/2026, 11:21:05)

Friendly and onversational

---

### **Assistant** (30/01/2026, 11:21:13)

Perfect, friendly and conversational it is!

**Should your agent use any tools or integrations?**

Based on what you described, it sounds like you'll need:

1. **Check availability** — Are you using Google Calendar, Calendly, or something else?
2. **Book/Reschedule/Cancel appointments** — Will this go through your FastAPI backend, or directly to a calendar system?
3. **Send SMS with payment link** — Through your FastAPI backend?

Essentially, should all these actions route to your **FastAPI backend** (and you handle the calendar/SMS logic there), or do you want direct integrations with Google Calendar, Calendly, etc.?

Also, what's your **FastAPI backend URL**? (e.g., `https://api.alltraders.com`)

---

### **You** (30/01/2026, 11:21:17)

female , australian accent

---

### **Assistant** (30/01/2026, 11:21:20)

Got it — friendly, conversational, female with an Australian accent!

Now back to the integrations question:

**How should the tools connect?**

You mentioned a FastAPI backend for DB integration. Should I route all the actions through your backend?

- **Check availability** → Your FastAPI endpoint
- **Book appointment** → Your FastAPI endpoint
- **Reschedule appointment** → Your FastAPI endpoint
- **Cancel appointment** → Your FastAPI endpoint
- **Send SMS with payment link** → Your FastAPI endpoint

If so, what's your **FastAPI backend base URL**? (e.g., `https://api.alltraders.com`)

Or would you prefer direct integrations with Google Calendar/Calendly for the calendar functions?

---

### **You** (30/01/2026, 11:23:13)

would prefer direct integration with gogle calendr/calendly if they are avaialble...but if not I will do it using my fastapi backend

---

### **Assistant** (30/01/2026, 11:23:15)

Vapi does have a **Google Calendar integration** built-in for checking availability and creating events. However, for the full flow you need (reschedule, cancel, send SMS), we'll likely use a hybrid approach:

**Direct Integration (Google Calendar):**
- ✅ Check availability
- ✅ Book appointments

**Your FastAPI Backend (for everything else):**
- Reschedule appointments
- Cancel appointments
- Send SMS with payment link

This gives you the best of both worlds — native calendar integration where possible, and your backend for custom logic.

---

**What's your FastAPI backend base URL?** (e.g., `https://api.alltraders.com`)

And one last question:

**Would you like to put this agent behind a phone number so you can call it?**

---

### **You** (30/01/2026, 11:23:58)

https://ava-ai-receptionist-production.up.railway.app/

---

### **Assistant** (30/01/2026, 11:24:01)

Got it.

**Would you like to put this agent behind a phone number so you can call it?**

If yes, what area code would you prefer? (Note: Free Vapi numbers are US-only. If you need an Australian number, you'd need to import one from Twilio.)

---

### **You** (30/01/2026, 11:24:40)

I havea twilio number already registered in australia

---

### **Assistant** (30/01/2026, 11:24:43)

Perfect! You can import your Twilio number after we create the agent.

Let me summarize what I'm about to build:

---

**All Traders AI Receptionist**

| Component | Configuration |
|:--|:--|
| **Personality** | Friendly, conversational |
| **Voice** | Female, Australian accent |
| **Tools** | Check availability (Google Calendar), Book appointment (Google Calendar), Reschedule appointment (FastAPI), Cancel appointment (FastAPI), Send SMS with payment link (FastAPI) |
| **Backend URL** | `https://ava-ai-receptionist-production.up.railway.app/` |

---

**Before I build this, one quick thing:**

For the Google Calendar integration to work, you'll need to connect your Google account in the Vapi Dashboard (Settings → Integrations → Google Calendar). Have you done that yet, or would you prefer I build all tools through your FastAPI backend for now?

Also, for your FastAPI tools, what are the **endpoint paths** for each action? For example:
- Reschedule: `/appointments/reschedule`
- Cancel: `/appointments/cancel`
- Send SMS: `/sms/payment-link`

And what **parameters** does each endpoint expect? (e.g., appointment ID, customer phone number, new date/time, etc.)

---

### **You** (30/01/2026, 11:28:50)

I can create the end points with the above paths in my fastapi end point.

---

### **Assistant** (30/01/2026, 11:28:53)

Let's define the parameters for each endpoint so I can build the tools correctly.

**What parameters should each endpoint expect?**

Here's a starting point — let me know if these work or need adjustments:

| Endpoint | Parameters |
|:--|:--|
| `/appointments/reschedule` | `appointment_id`, `new_date`, `new_time` |
| `/appointments/cancel` | `appointment_id` |
| `/sms/payment-link` | `phone_number`, `amount`, `appointment_id` |

Does this look right? Or do you need different/additional parameters (like `customer_name`, `service_type`, etc.)?

---

### **You** (30/01/2026, 11:29:37)

I want to include the business_id as well. Remember this is for a multi-tenant agent platform. Do you want to reconsider the architecutre?

---

### **Assistant** (30/01/2026, 11:29:40)

Ah, this is a crucial detail! A **multi-tenant agent platform** changes things significantly.

Let me think through the architecture options:

---

### Option 1: Single Agent + Dynamic Business Context
- One assistant that handles all businesses
- Pass `business_id` dynamically at call time (via `variableValues`)
- All tools receive `business_id` to route to the correct tenant
- **Pros:** Easier to maintain, one assistant to update
- **Cons:** System prompt needs to be generic, can't customize per business

### Option 2: One Agent Per Business
- Create a separate assistant for each business
- Each has its own name, personality, business-specific instructions
- `business_id` is baked into each assistant's tool configurations
- **Pros:** Fully customizable per tenant, business-specific prompts
- **Cons:** More assistants to manage

### Option 3: Squad-Based (Recommended for Scale)
- A lightweight "router" agent that identifies the business
- Hands off to business-specific assistants
- **Pros:** Clean separation, scalable
- **Cons:** More complex setup

---

**For a multi-tenant platform, I'd recommend Option 2** — create assistants programmatically per business via your backend when a new business signs up. Each assistant gets its own phone number and business-specific configuration.

**Questions:**
1. Which option fits your vision?
2. Should `business_id` come from the **phone number called** (each business has their own number), or passed some other way?
3. Do businesses need different voices/personalities, or all the same?

---

### **You** (30/01/2026, 11:31:30)

1. I think will go with option 2.  2. phone number alled  3. yes, they might differ based on the tenant

---

### **Assistant** (30/01/2026, 11:31:33)

Excellent choices! Option 2 with phone number routing makes the most sense for a multi-tenant platform.

Here's the refined architecture:

---

### Multi-Tenant Architecture

```
Inbound Call → Phone Number → Assistant (Business-Specific)
                    ↓
              business_id embedded in assistant config
                    ↓
              Tools pass business_id to your FastAPI backend
```

**Each business gets:**
- Their own **Assistant** (custom name, voice, personality, instructions)
- Their own **Phone Number** (mapped to that assistant)
- Their own **business_id** baked into tool calls

---

### What I'll Build Now (Template)

I'll create a **template assistant** for you that demonstrates the pattern. You can then programmatically clone/create new assistants per tenant via the API.

**Updated Tool Parameters:**

| Endpoint | Parameters |
|:--|:--|
| `/appointments/reschedule` | `business_id`, `appointment_id`, `new_date`, `new_time` |
| `/appointments/cancel` | `business_id`, `appointment_id`, `reason` (optional) |
| `/sms/payment-link` | `business_id`, `phone_number`, `amount`, `appointment_id` |

**For Google Calendar tools**, we'll also need a way to identify which calendar belongs to which business. Options:
- Pass `business_id` and your backend returns the calendar ID
- Or route calendar actions through your FastAPI too (so you control which calendar)

**Which do you prefer?** Route calendar actions through FastAPI (gives you full control), or use direct Google Calendar integration?

---

### **You** (30/01/2026, 11:32:35)

will take FAst API route

---

### **Assistant** (30/01/2026, 11:32:39)

Smart choice! Full control through your FastAPI backend. This keeps everything consistent and lets you manage calendar integrations per tenant on your end.

---

### Final Tool Design

| Endpoint | Parameters |
|:--|:--|
| `/appointments/check-availability` | `business_id`, `date`, `service_type` (optional) |
| `/appointments/book` | `business_id`, `customer_name`, `customer_phone`, `date`, `time`, `service_type` |
| `/appointments/reschedule` | `business_id`, `appointment_id`, `new_date`, `new_time` |
| `/appointments/cancel` | `business_id`, `appointment_id`, `reason` (optional) |
| `/sms/payment-link` | `business_id`, `phone_number`, `amount`, `appointment_id` |

---

**Ready to build!**

I'll create:
1. **5 tools** pointing to your FastAPI backend
2. **1 template assistant** (friendly, conversational, female Australian accent) with a placeholder `business_id` you can override per tenant

The `business_id` will be set as a template variable (`business_id}}`) so when you create calls or assign assistants to phone numbers, you pass the actual business ID.

**Sound good?** I'll set this up now.

---

### **You** (30/01/2026, 11:33:21)

'sure

---

### **Assistant** (30/01/2026, 11:33:24)

Let me build this out for you now. I'll create the 5 tools first, then the template assistant.

---

### **Assistant** (30/01/2026, 11:33:25)



---

### **Assistant** (30/01/2026, 11:33:28)



---

### **Assistant** (30/01/2026, 11:33:31)



---

### **Assistant** (30/01/2026, 11:33:34)



---

### **Assistant** (30/01/2026, 11:33:36)



---

### **Assistant** (30/01/2026, 11:33:42)

All 5 tools created. Now let me generate a professional system prompt and create the template assistant.

---

### **Assistant** (30/01/2026, 11:33:43)



---

### **Assistant** (30/01/2026, 11:34:04)

Now let me create the template assistant with this prompt and the tools:

---

### **Assistant** (30/01/2026, 11:34:04)



---

### **Assistant** (30/01/2026, 11:34:22)

Your AI receptionist is ready! Here's what I built:

---

## ✅ All Traders AI Receptionist - Complete!

### Template Assistant
| Field | Value |
|:--|:--|
| **ID** | `f196116e-5d00-4b2b-b6a9-4d59d0c6f223` |
| **Name** | All Traders AI Receptionist (Template) |
| **Voice** | ElevenLabs - Female Australian accent |
| **Model** | GPT-4o |
| **Transcriber** | Deepgram Nova-2 (Australian English) |

### Tools Created

| Tool | ID | Endpoint |
|:--|:--|:--|
| **Check Availability** | `3e7dfce6-82aa-4b32-b576-781773493646` | `/appointments/check-availability` |
| **Book Appointment** | `00def14a-ca11-4e9b-8156-876e1897b986` | `/appointments/book` |
| **Reschedule Appointment** | `92ba1764-8f54-4c02-a0eb-8f4dd9ca02d2` | `/appointments/reschedule` |
| **Cancel Appointment** | `0d24618e-abd3-4e71-989c-f25d1e7f57ae` | `/appointments/cancel` |
| **Send Payment Link** | `fe8eb6d5-d85d-49c7-9a44-6d351b954ef8` | `/sms/payment-link` |

---

## Template Variables

When creating assistants for each tenant, pass these variables:

| Variable | Description | Example |
|:--|:--|:--|
| `{{business_id}}` | Unique tenant identifier | `biz_12345` |
| `{{business_name}}` | Display name of the business | `Smith's Plumbing` |
| `{{business_type}}` | Type of trade/service | `plumbing` |

---

## Next Steps

### 1. Import Your Twilio Number
Go to **Phone Numbers** in the sidebar and import your Australian Twilio number, then attach this assistant to it.

### 2. Implement Your FastAPI Endpoints
Your backend needs these endpoints (all receive POST with JSON):

```python
# Expected request format for all endpoints
{
    "message": {
        "toolCallList": [{
            "function": {
                "name": "check_availability",
                "arguments": {
                    "business_id": "biz_123",
                    "date": "2024-02-15"
                }
            }
        }]
    }
}

# Expected response format
{
    "results": [{
        "result": "Available slots: 9:00 AM, 11:30 AM, 2:00 PM"
    }]
}
```

### 3. Create Tenant Assistants Programmatically
When a new business signs up, clone this template via API with their specific `variableValues`.

---

Would you like me to:
1. **Run an eval** to test this assistant works correctly?
2. **Show you the API call** to create a new tenant-specific assistant?
3. **Help import your Twilio number**?