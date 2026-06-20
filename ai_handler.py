import os
import re
import json
import requests
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

# ============================================================
# CLINIC KNOWLEDGE BASE
# ============================================================
CLINIC_INFO = """
Clinic Name: SmileCare Dental Clinic
Location: 42, Main Market Road, Lajpat Nagar, New Delhi - 110024
Phone: +91 98765 43210
Email: smilecare@gmail.com

Working Hours:
- Monday to Saturday: 9:00 AM to 8:00 PM
- Sunday: 10:00 AM to 2:00 PM (Emergency only)

Services:
- Teeth Cleaning
- Dental Fillings
- Teeth Alignment
- Root Canal Treatment
- Tooth Extraction
- Teeth Whitening

Doctors:
- Dr. Priya Sharma (BDS, MDS) - Lead Dentist, 12 years experience
- Dr. Arjun Mehta (BDS) - General Dentist, 5 years experience

Payment: Cash, UPI, All major cards accepted
Parking: Available

Important Notes:
- Appointments are 30-45 minutes typically
- Please arrive 5 minutes early
- Carry any previous dental records if available
"""

# ============================================================
# MAIN AI FUNCTION — INTENT BASED
# ============================================================
def get_bota_response(user_message, conversation_history=None):

    history_text = ""
    if conversation_history:
        for msg in conversation_history[-6:]:
            role = "User" if msg["role"] == "user" else "Bota"
            history_text += f"{role}: {msg['content']}\n"

    prompt = f"""You are Bota, a friendly and smart AI assistant for SmileCare Dental Clinic.

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

    greetings = ["hi", "hello", "hey", "namaste", "hlo", "hii"]
    if any(g in text_lower for g in greetings):
        return {
            "intent": "greeting",
            "reply": "Hi there! I am Bota, your assistant at SmileCare Dental Clinic. I can help you book an appointment or answer questions about our clinic. How can I help you today?",
            "booking_data": None
        }

    booking_keywords = ["book", "appointment", "schedule", "fix", "slot", "visit", "checkup", "consultation"]
    if any(k in text_lower for k in booking_keywords):
        name_match = re.search(r"(?:my name is|name is|for|i am|i'm)\s+([A-Za-z]+)", text, re.IGNORECASE)
        time_match = re.search(r'(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))', text)
        date_match = re.search(r'(tomorrow|today|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*|\d{1,2}[\/\-]\d{1,2})', text, re.IGNORECASE)

        name = name_match.group(1) if name_match else ""
        time = time_match.group(1).upper() if time_match else ""
        date = date_match.group(1) if date_match else ""

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