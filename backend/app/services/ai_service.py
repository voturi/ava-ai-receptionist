from openai import OpenAI
import os
import json
from typing import Optional, Dict, Any

class AIService:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = "gpt-4-turbo-preview"
    
    def get_system_prompt(self, business_name: str = "our business") -> str:
        """
        System prompt that defines AI behavior
        """
        return f"""You are Sarah, the AI receptionist for {business_name}, a premium hair salon in Bondi, Sydney.

        YOUR PERSONALITY:
        - Warm, friendly, and professional
        - Use Australian expressions naturally: "no worries", "lovely", "arvo"
        - Speak like you're having a friendly chat, not reading a script
        - Keep responses conversational and SHORT (15-20 words max)

        BOOKING PROCESS:
        When someone wants to book:
        1. Ask what service (cut, color, balayage, etc.)
        2. Ask preferred day (be flexible: "this week? next week?")
        3. Ask preferred time (morning, arvo, specific time)
        4. Get their name
        5. Get phone number (for SMS confirmation)
        6. Repeat back details to confirm
        7. Confirm booking

        EXAMPLE CONVERSATION:
        Customer: "I need a haircut"
        You: "No worries! When would suit you? This week or next?"
        Customer: "Wednesday afternoon"
        You: "Lovely! What time - 2pm, 3pm, or 4pm?"
        Customer: "2pm works"
        You: "Perfect! And your name?"
        Customer: "Sarah"
        You: "Great Sarah! Phone number for SMS confirmation?"
        Customer: "0412 345 678"
        You: "Brilliant! So that's a haircut Wednesday 2pm. I'll SMS you soon. All sorted!"

        IMPORTANT RULES:
        - Never make up prices or policies
        - If you don't know, say "Let me check with the team" and offer to transfer
        - If customer sounds frustrated, apologize warmly and transfer
        - Always confirm details before finalizing
        - Sound human, not robotic!
        """
    
    async def get_response(
        self, 
        user_message: str,
        conversation_history: list = None,
        business_name: str = "our business"
    ) -> Dict[str, Any]:
        """
        Get AI response to user message
        
        Returns:
            {
                "text": "AI response text",
                "intent": "booking|inquiry|other",
                "collected_data": {...},
                "should_transfer": bool
            }
        """
        if conversation_history is None:
            conversation_history = []
        
        # Build messages
        messages = [
            {"role": "system", "content": self.get_system_prompt(business_name)}
        ]
        
        # Add conversation history
        messages.extend(conversation_history)
        
        # Add current user message
        messages.append({"role": "user", "content": user_message})
        
        # Call OpenAI
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=150,
                temperature=0.7,
            )
            
            ai_text = response.choices[0].message.content
            
            # Simple intent detection (we'll improve this later)
            intent = self._detect_intent(user_message, ai_text)
            
            # Extract any data mentioned
            collected_data = self._extract_booking_data(user_message)
            
            return {
                "text": ai_text,
                "intent": intent,
                "collected_data": collected_data,
                "should_transfer": "transfer" in ai_text.lower()
            }
            
        except Exception as e:
            print(f"❌ OpenAI Error: {e}")
            return {
                "text": "I'm having a technical issue. Let me transfer you to someone who can help.",
                "intent": "error",
                "collected_data": {},
                "should_transfer": True
            }
    
    def _detect_intent(self, user_msg: str, ai_response: str) -> str:
        """Simple intent detection"""
        user_lower = user_msg.lower()
        
        booking_keywords = ["book", "appointment", "schedule", "reserve", "haircut", "color"]
        inquiry_keywords = ["price", "cost", "how much", "hours", "open", "location"]
        
        if any(word in user_lower for word in booking_keywords):
            return "booking"
        elif any(word in user_lower for word in inquiry_keywords):
            return "inquiry"
        else:
            return "other"
    
    def _extract_booking_data(self, text: str) -> Dict[str, Any]:
        """
        Extract booking information from text
        (Simple version - we'll improve with better NLP later)
        """
        data = {}
        text_lower = text.lower()
        
        # Detect service mentions
        if "haircut" in text_lower or "cut" in text_lower:
            data["service"] = "haircut"
        elif "color" in text_lower or "colour" in text_lower:
            data["service"] = "color"
        elif "balayage" in text_lower:
            data["service"] = "balayage"
        
        # Detect time mentions (simple)
        time_keywords = {
            "morning": "morning",
            "afternoon": "afternoon", 
            "arvo": "afternoon",
            "evening": "evening",
            "lunch": "lunchtime"
        }
        
        for keyword, value in time_keywords.items():
            if keyword in text_lower:
                data["time_preference"] = value
        
        return data

# Create singleton instance
ai_service = AIService()
 

 