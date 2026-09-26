from pathlib import Path
from datetime import datetime, timezone
import base64
import hashlib
import hmac
import json
import os
import secrets

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponseStreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional

from ai_handler import get_bota_response
from database import (
    add_appointment,
    get_appointments,
    delete_appointment,
    init_db,
    get_setting,
    set_setting,
)
from config import (
    CLINIC_NAME,
    ADMIN_USERNAME,
    ADMIN_PASSWORD,
    ADMIN_SESSION_SECRET,
    CLINIC_OPEN_HOUR,
    CLINIC_CLOSE_HOUR,
)

BASE_DIR = Path(__file__).resolve().parent
INDEX_FILE = BASE_DIR / "index.html"
ADMIN_FILE = BASE_DIR / "admin.html"

IS_VERCEL = bool(os.getenv("VERCEL"))

if IS_VERCEL and not ADMIN_SESSION_SECRET:
    raise RuntimeError("ADMIN_SESSION_SECRET must be set in Vercel Environment Variables")

if IS_VERCEL and (not ADMIN_PASSWORD or ADMIN_PASSWORD == "changeme123"):
    raise RuntimeError("Set a real ADMIN_PASSWORD in Vercel Environment Variables")

# Initialise the database on cold start.
init_db()

app = FastAPI(title="Bota - AI Appointment Assistant")

# Same-origin deployment does not need CORS, but keeping this permissive
# allows the local HTML/API workflow to continue working during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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
        extra = "ignore"


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# ============================================================
# ADMIN SESSION AUTHENTICATION
# ============================================================
SESSION_COOKIE = "bota_admin_session"
SESSION_MAX_AGE = 60 * 60 * 8  # 8 hours


def _session_secret() -> bytes:
    # Local development fallback. Production requires ADMIN_SESSION_SECRET.
    secret = ADMIN_SESSION_SECRET or ADMIN_PASSWORD or secrets.token_urlsafe(32)
    return secret.encode("utf-8")


def _make_session(username: str) -> str:
    payload = {
        "username": username,
        "exp": int(datetime.now(timezone.utc).timestamp()) + SESSION_MAX_AGE,
        "nonce": secrets.token_urlsafe(12),
    }
    raw = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(
        _session_secret(), raw.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{raw}.{signature}"


def _read_session(token: str | None):
    if not token or "." not in token:
        return None

    raw, signature = token.rsplit(".", 1)
    expected = hmac.new(
        _session_secret(), raw.encode("ascii"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        return None

    try:
        padded = raw + "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if payload.get("username") != ADMIN_USERNAME:
            return None
        if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def require_admin(request: Request):
    session = _read_session(request.cookies.get(SESSION_COOKIE))
    if not session:
        raise HTTPException(status_code=401, detail="Admin authentication required")
    return session


def get_current_admin_password():
    return get_setting("admin_password", ADMIN_PASSWORD)


# ============================================================
# PUBLIC ROUTES
# ============================================================
@app.get("/")
def home():
    return RedirectResponse(url="/ui")


@app.get("/ui")
def serve_ui():
    return FileResponse(INDEX_FILE)


@app.get("/admin")
def serve_admin():
    return FileResponse(ADMIN_FILE)


@app.get("/clinic-config")
def get_clinic_config():
    return {
        "clinic_name": CLINIC_NAME,
        "open_hour": CLINIC_OPEN_HOUR,
        "close_hour": CLINIC_CLOSE_HOUR,
    }


@app.post("/admin-login")
def admin_login(req: LoginRequest):
    if (
        req.username != ADMIN_USERNAME
        or req.password != get_current_admin_password()
    ):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    response = JSONResponse({"success": True})
    response.set_cookie(
        key=SESSION_COOKIE,
        value=_make_session(req.username),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=IS_VERCEL,
        samesite="lax",
        path="/",
    )
    return response


@app.post("/admin-logout")
def admin_logout():
    response = JSONResponse({"success": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


# ============================================================
# PUBLIC CHAT / BOOKING ROUTES
# ============================================================
@app.post("/chat")
def chat(req: ChatRequest):
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    ai_result = get_bota_response(req.message, req.conversation_history)
    intent = ai_result.get("intent", "irrelevant")
    reply = ai_result.get("reply", "I'm here to help! 😊")
    booking_data = ai_result.get("booking_data")

    if intent == "booking" and booking_data:
        saved, error = add_appointment(booking_data)
        if error:
            return {
                "intent": "booking_failed",
                "reply": f"⚠️ {error}",
                "appointment": None,
            }
        return {
            "intent": "booking_confirmed",
            "reply": reply,
            "appointment": saved,
        }

    return {
        "intent": intent,
        "reply": reply,
        "appointment": None,
    }


@app.post("/book")
def book_appointment(data: AppointmentRequest):
    saved, error = add_appointment(data.model_dump())
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {
        "message": "Appointment booked successfully ✅",
        "appointment": saved,
    }


# ============================================================
# PROTECTED ADMIN ROUTES
# ============================================================
@app.post("/admin-change-password")
def admin_change_password(req: ChangePasswordRequest, request: Request):
    require_admin(request)

    if req.current_password != get_current_admin_password():
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(req.new_password) < 6:
        raise HTTPException(
            status_code=400,
            detail="New password must be at least 6 characters",
        )

    set_setting("admin_password", req.new_password)
    return {"success": True}


@app.get("/appointments")
def view_appointments(request: Request):
    require_admin(request)
    return get_appointments()


@app.delete("/appointments/{appointment_id}")
def cancel_appointment(appointment_id: int, request: Request):
    require_admin(request)
    success = delete_appointment(appointment_id)
    if not success:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return {"message": "Appointment cancelled ✅"}


@app.get("/appointments/export")
def export_appointments(request: Request):
    require_admin(request)

    appointments = get_appointments()

    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID",
        "Name",
        "Age",
        "Phone",
        "Date",
        "Time",
        "Service",
        "Status",
        "Created At",
    ])

    for appointment in appointments:
        writer.writerow([
            appointment.get("id", ""),
            appointment.get("name", ""),
            appointment.get("age", ""),
            appointment.get("phone", ""),
            appointment.get("date", ""),
            appointment.get("time", ""),
            appointment.get("service", ""),
            appointment.get("status", ""),
            appointment.get("created_at", ""),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=bota_appointments.csv"
        },
    )
