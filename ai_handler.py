import os
import re
import json
import requests
from config import GEMINI_API_KEY, CLINIC_NAME, build_clinic_info_text

GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

# ============================================================
# CLINIC KNOWLEDGE BASE — built dynamically from config.py
# (which reads environment variables set per clinic)
# ============================================================
CLINIC_INFO = build_clinic_info_text()

# ============================================================
# MAIN AI FUNCTION — INTENT BASED
# ============================================================
def get_bota_response(user_message, conversation_history=None):

    history_text = ""
    if conversation_history:
        for msg in conversation_history[-6:]:
            role = "User" if msg["role"] == "user" else "Bota"
            history_text += f"{role}: {msg['content']}\n"

    prompt = f"""You are Bota, a friendly and smart AI assistant for {CLINIC_NAME}.

CLINIC INFORMATION:
{CLINIC_INFO}

CONVERSATION SO FAR:
{history_text}
User: {user_message}

YOUR JOB:
1. Understand what the user wants.
2. If they want to BOOK an appointment → extract name, date, time. If any detail is missing, ask for it politely.
3. If they ask about the CLINIC (timings, services, cost, location, doctors) → answer from clinic info.
4. If the message is a GREETING → greet back warmly and offer help.
5. If the message is NOT related to the clinic or dental topics, or is random/unclear text → reply warmly saying you didn't understand and guide them to choose from booking, services, or timings.

RESPOND ONLY IN THIS EXACT JSON FORMAT (no extra text, no markdown, no backticks):
{{"intent": "booking" or "clinic_info" or "greeting" or "irrelevant" or "incomplete_booking" (use irrelevant for random/unclear text too), "reply": "your friendly reply here", "booking_data": {{"name": "", "date": "", "time": "", "service": ""}}}}

RULES:
- booking_data should only be filled if intent is "booking" AND you have name + date + time
- If booking details are partial, set intent to "incomplete_booking" and ask for missing info
- Keep replies warm, concise, professional
- Use Hindi words occasionally like Ji, bilkul to feel local and friendly
- Understand common Hinglish/Hindi words for dates and times: "kal"=tomorrow, "aaj"=today,
  "parso"=day after tomorrow, "subah"=morning, "shaam"=evening, "dopahar"=afternoon, "raat"=night.
  Convert these to standard English date/time in booking_data.
- Be tolerant of typos and informal spelling — infer the intended meaning
- NEVER make up information not in the clinic info
- Only return valid JSON, nothing else, no markdown, no backticks
"""

    try:
        response = requests.post(
            GEMINI_URL,
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": 500
                }
            },
            timeout=15
        )

        result = response.json()

        # Gemini sometimes blocks/filters content and returns no candidates
        if "candidates" not in result or not result["candidates"]:
            print("GEMINI WARNING: No candidates in response —", result.get("promptFeedback", "no feedback info"))
            return fallback_handler(user_message)

        # Extract text from Gemini response
        ai_text = result["candidates"][0]["content"]["parts"][0]["text"].strip()

        print("RAW GEMINI OUTPUT:", ai_text)

        # Clean markdown if Gemini adds it
        ai_text = ai_text.replace("```json", "").replace("```", "").strip()

        # Extract JSON
        match = re.search(r'\{.*\}', ai_text, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            return parsed

        return fallback_handler(user_message)

    except Exception as e:
        print("GEMINI ERROR:", str(e))
        return fallback_handler(user_message)


# ============================================================
# FALLBACK — when Gemini fails or returns bad output
# ============================================================
def fallback_handler(text):
    print("Using fallback handler")

    text_lower = text.lower()

    greetings = ["hi", "hello", "hey", "namaste", "hlo", "hii", "namaskar", "hola"]
    if any(g in text_lower for g in greetings):
        return {
            "intent": "greeting",
            "reply": f"Hi there! I am Bota, your assistant at {CLINIC_NAME}. I can help you book an appointment or answer questions about our clinic. How can I help you today?",
            "booking_data": None
        }

    booking_keywords = [
        "book", "appointment", "schedule", "fix", "slot", "visit", "checkup", "consultation",
        "appointment chahiye", "milna hai", "dikhana hai", "checkup karana hai", "time chahiye"
    ]
    if any(k in text_lower for k in booking_keywords):
        name_match = re.search(r"(?:my name is|name is|for|i am|i'm|mera naam)\s+([A-Za-z]+)", text, re.IGNORECASE)
        time_match = re.search(r'(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))', text)

        # Hinglish date/time words mapped to English equivalents
        hinglish_dates = {
            "kal": "tomorrow", "aaj": "today", "parso": "day after tomorrow"
        }
        hinglish_time = {
            "subah": "morning", "shaam": "evening", "dopahar": "afternoon", "raat": "night"
        }

        date = ""
        for hindi_word, eng in hinglish_dates.items():
            if hindi_word in text_lower:
                date = eng
                break
        if not date:
            date_match = re.search(r'(tomorrow|today|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*|\d{1,2}[\/\-]\d{1,2})', text, re.IGNORECASE)
            date = date_match.group(1) if date_match else ""

        name = name_match.group(1) if name_match else ""
        time = time_match.group(1).upper() if time_match else ""

        if name and time and date:
            return {
                "intent": "booking",
                "reply": f"Perfect! Let me confirm — {name} on {date} at {time}. Booking it right away!",
                "booking_data": {"name": name, "date": date, "time": time, "service": ""}
            }
        else:
            missing = []
            if not name: missing.append("your name")
            if not date: missing.append("preferred date")
            if not time: missing.append("preferred time")
            return {
                "intent": "incomplete_booking",
                "reply": f"I would love to help you book! Could you please share {', '.join(missing)}?",
                "booking_data": None
            }

    info_keywords = ["timing", "time", "open", "close", "service", "location", "address", "where"]
    if any(k in text_lower for k in info_keywords):
        return {
            "intent": "clinic_info",
            "reply": "I can help with that! You can ask me about our timings, services, costs, doctors or location. What would you like to know specifically?",
            "booking_data": None
        }

    return {
        "intent": "irrelevant",
        "reply": "I didn't quite understand that 😊 I can help you with booking an appointment, our services, or clinic timings. What would you like to do?",
        "booking_data": None
    }