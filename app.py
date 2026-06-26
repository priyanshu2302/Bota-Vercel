from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import os
from dotenv import load_dotenv

from ai_handler import get_bota_response
from database import add_appointment, get_appointments, delete_appointment, init_db

load_dotenv()

# Init DB on startup
init_db()

app = FastAPI(title="Bota - AI Appointment Assistant")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# SCHEMAS
# ============================================================
class ChatRequest(BaseModel):
    message: str
    conversation_history: Optional[list] = []

class AppointmentRequest(BaseModel):
    name: str
    age: Optional[str] = ""
    date: str
    time: str
    service: Optional[str] = "General Consultation"

    class Config:
        extra = "ignore"  # silently ignore unexpected fields instead of 400 error

# ============================================================
# ROUTES
# ============================================================

@app.get("/")
def home():
    return {"message": "Bota AI Appointment Assistant is Running 🚀", "status": "ok"}

@app.get("/ui")
def serve_ui():
    return FileResponse("index.html")

@app.get("/admin")
def serve_admin():
    return FileResponse("admin.html")

# Main chat endpoint — handles everything
@app.post("/chat")
def chat(req: ChatRequest):
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Get AI response
    ai_result = get_bota_response(req.message, req.conversation_history)

    intent = ai_result.get("intent", "irrelevant")
    reply = ai_result.get("reply", "I'm here to help! 😊")
    booking_data = ai_result.get("booking_data")

    # If booking intent and we have all details → save it
    if intent == "booking" and booking_data:
        saved, error = add_appointment(booking_data)

        if error:
            # Slot taken or missing fields
            return {
                "intent": "booking_failed",
                "reply": f"⚠️ {error}",
                "appointment": None
            }

        return {
            "intent": "booking_confirmed",
            "reply": reply,
            "appointment": saved
        }

    return {
        "intent": intent,
        "reply": reply,
        "appointment": None
    }

# Manual booking endpoint (for direct form submissions if needed)
@app.post("/book")
def book_appointment(data: AppointmentRequest):
    saved, error = add_appointment(data.dict())
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {
        "message": "Appointment booked successfully ✅",
        "appointment": saved
    }

# View all appointments (admin)
@app.get("/appointments")
def view_appointments():
    return get_appointments()

# Cancel appointment
@app.delete("/appointments/{appointment_id}")
def cancel_appointment(appointment_id: int):
    success = delete_appointment(appointment_id)
    if not success:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return {"message": "Appointment cancelled ✅"}