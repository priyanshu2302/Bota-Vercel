from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from ai_handler import get_bota_response
from database import add_appointment, get_appointments, delete_appointment, init_db, get_setting, set_setting
from config import CLINIC_NAME, ADMIN_USERNAME, ADMIN_PASSWORD, CLINIC_OPEN_HOUR, CLINIC_CLOSE_HOUR

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
    phone: Optional[str] = ""
    date: str
    time: str
    service: Optional[str] = "General Consultation"

    class Config:
        extra = "ignore"  # silently ignore unexpected fields instead of 400 error

class LoginRequest(BaseModel):
    username: str
    password: str

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

# Clinic config — frontend fetches this so HTML never hardcodes clinic name
@app.get("/clinic-config")
def get_clinic_config():
    return {
        "clinic_name": CLINIC_NAME,
        "open_hour": CLINIC_OPEN_HOUR,
        "close_hour": CLINIC_CLOSE_HOUR
    }

# Admin login — checked server-side, password persisted in the database so
# changes survive server restarts/redeploys. Falls back to ADMIN_PASSWORD
# (from environment variables) if no password has been set in the database yet.
def get_current_admin_password():
    return get_setting("admin_password", ADMIN_PASSWORD)

@app.post("/admin-login")
def admin_login(req: LoginRequest):
    if req.username == ADMIN_USERNAME and req.password == get_current_admin_password():
        return {"success": True}
    raise HTTPException(status_code=401, detail="Invalid username or password")

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

# Change admin password — persisted in the database, survives server restarts
# and redeploys. Overrides the ADMIN_PASSWORD environment variable once set.
@app.post("/admin-change-password")
def admin_change_password(req: ChangePasswordRequest):
    if req.current_password != get_current_admin_password():
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    set_setting("admin_password", req.new_password)
    return {"success": True}

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

# Export all appointments as CSV — opens directly in Excel
@app.get("/appointments/export")
def export_appointments():
    import csv
    import io
    from fastapi.responses import StreamingResponse

    appointments = get_appointments()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Name", "Age", "Phone", "Date", "Time", "Service", "Status", "Created At"])

    for a in appointments:
        writer.writerow([
            a.get("id", ""),
            a.get("name", ""),
            a.get("age", ""),
            a.get("phone", ""),
            a.get("date", ""),
            a.get("time", ""),
            a.get("service", ""),
            a.get("status", ""),
            a.get("created_at", "")
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bota_appointments.csv"}
    )