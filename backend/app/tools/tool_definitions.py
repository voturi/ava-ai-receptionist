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
                    "business_id": {"type": "string"},
                    "customer_phone": {"type": "string"},
                },
                "required": ["business_id", "customer_phone"],
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
                    "business_id": {"type": "string"},
                    "booking_id": {"type": "string"},
                },
                "required": ["business_id", "booking_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_business_services",
            "description": "Get the list of services offered by a business.",
            "parameters": {
                "type": "object",
                "properties": {
                    "business_id": {"type": "string"},
                },
                "required": ["business_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_working_hours",
            "description": "Get working hours for a business.",
            "parameters": {
                "type": "object",
                "properties": {
                    "business_id": {"type": "string"},
                },
                "required": ["business_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_policies",
            "description": "Get policies for a business by topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "business_id": {"type": "string"},
                    "topic": {"type": "string"},
                },
                "required": ["business_id", "topic"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_faqs",
            "description": "Get FAQs for a business by topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "business_id": {"type": "string"},
                    "topic": {"type": "string"},
                },
                "required": ["business_id", "topic"],
                "additionalProperties": False,
            },
        },
    },
]
