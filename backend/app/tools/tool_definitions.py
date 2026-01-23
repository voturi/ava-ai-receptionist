from __future__ import annotations

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_latest_booking",
            "description": "Get the most recent booking for a customer by phone number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_phone": {"type": "string"},
                },
                "required": ["customer_phone"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_booking_by_id",
            "description": "Get booking details by booking ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                },
                "required": ["booking_id"],
                "additionalProperties": False,
            },
        },
    },
    # Tools below are intentionally disabled for MVP.
    # Policies/FAQs are injected into the prompt context for SMBs.
    # Re-enable later when dynamic retrieval is needed.
    # {
    #     "type": "function",
    #     "function": {
    #         "name": "get_business_services",
    #         "description": "Get the list of services offered by a business.",
    #         "parameters": {
    #             "type": "object",
    #             "properties": {},
    #             "required": [],
    #             "additionalProperties": False,
    #         },
    #     },
    # },
    # {
    #     "type": "function",
    #     "function": {
    #         "name": "get_working_hours",
    #         "description": "Get working hours for a business.",
    #         "parameters": {
    #             "type": "object",
    #             "properties": {},
    #             "required": [],
    #             "additionalProperties": False,
    #         },
    #     },
    # },
    # {
    #     "type": "function",
    #     "function": {
    #         "name": "get_policies",
    #         "description": "Get policies for a business by topic.",
    #         "parameters": {
    #             "type": "object",
    #             "properties": {
    #                 "topic": {"type": "string"},
    #             },
    #             "required": ["topic"],
    #             "additionalProperties": False,
    #         },
    #     },
    # },
    # {
    #     "type": "function",
    #     "function": {
    #         "name": "get_faqs",
    #         "description": "Get FAQs for a business by topic.",
    #         "parameters": {
    #             "type": "object",
    #             "properties": {
    #                 "topic": {"type": "string"},
    #             },
    #             "required": ["topic"],
    #             "additionalProperties": False,
    #         },
    #     },
    # },
]
