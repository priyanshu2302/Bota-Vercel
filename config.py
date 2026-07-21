import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CLINIC CONFIGURATION — ALL FROM ENVIRONMENT VARIABLES
# ============================================================
# This is the ONLY file that needs different values per clinic.
# Set these as Environment Variables on Render for each deployment.
# Locally, set them in your .env file.
# ============================================================

CLINIC_NAME      = os.getenv("CLINIC_NAME", "SmileCare Dental Clinic")
CLINIC_ADDRESS   = os.getenv("CLINIC_ADDRESS", "42, Main Market Road, Lajpat Nagar, New Delhi - 110024")
CLINIC_PHONE     = os.getenv("CLINIC_PHONE", "+91 98765 43210")
CLINIC_EMAIL     = os.getenv("CLINIC_EMAIL", "smilecare@gmail.com")

CLINIC_HOURS_WEEKDAY = os.getenv("CLINIC_HOURS_WEEKDAY", "Monday to Saturday: 9:00 AM to 8:00 PM")
CLINIC_HOURS_SUNDAY  = os.getenv("CLINIC_HOURS_SUNDAY", "Sunday: 10:00 AM to 2:00 PM (Emergency only)")

# ── BOOKING VALIDATION HOURS (24-hour format, used for time validation) ──
# Change these per clinic if their opening/closing time is different.
CLINIC_OPEN_HOUR  = int(os.getenv("CLINIC_OPEN_HOUR", "9"))   # 9 = 9 AM
CLINIC_CLOSE_HOUR = int(os.getenv("CLINIC_CLOSE_HOUR", "20")) # 20 = 8 PM

# Services — comma separated in env var, e.g. "Teeth Cleaning,Dental Fillings,Root Canal"
CLINIC_SERVICES = os.getenv(
    "CLINIC_SERVICES",
    "Teeth Cleaning,Dental Fillings,Teeth Alignment,Root Canal Treatment,Tooth Extraction,Teeth Whitening"
).split(",")

# Doctors — format: "Name|Qualification|Experience;Name2|Qualification2|Experience2"
CLINIC_DOCTORS_RAW = os.getenv(
    "CLINIC_DOCTORS",
    "Dr. Priya Sharma|BDS, MDS|Lead Dentist, 12 years experience;Dr. Arjun Mehta|BDS|General Dentist, 5 years experience"
)

def get_doctors_list():
    """Parses CLINIC_DOCTORS_RAW into a list of dicts."""
    doctors = []
    for entry in CLINIC_DOCTORS_RAW.split(";"):
        parts = entry.split("|")
        if len(parts) == 3:
            doctors.append({"name": parts[0].strip(), "qualification": parts[1].strip(), "experience": parts[2].strip()})
    return doctors

CLINIC_PAYMENT  = os.getenv("CLINIC_PAYMENT", "Cash, UPI, All major cards accepted")
CLINIC_PARKING  = os.getenv("CLINIC_PARKING", "Available")

# ============================================================
# ADMIN LOGIN — per clinic
# ============================================================
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme123")

# ============================================================
# GEMINI API KEY
# ============================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


def build_clinic_info_text():
    """Builds the full clinic info text block used in the AI prompt."""
    services_text = "\n".join([f"- {s.strip()}" for s in CLINIC_SERVICES])
    doctors_text = "\n".join([
        f"- {d['name']} ({d['qualification']}) - {d['experience']}"
        for d in get_doctors_list()
    ])

    return f"""
Clinic Name: {CLINIC_NAME}
Location: {CLINIC_ADDRESS}
Phone: {CLINIC_PHONE}
Email: {CLINIC_EMAIL}

Working Hours:
- {CLINIC_HOURS_WEEKDAY}
- {CLINIC_HOURS_SUNDAY}

Services:
{services_text}

Doctors:
{doctors_text}

Payment: {CLINIC_PAYMENT}
Parking: {CLINIC_PARKING}

Important Notes:
- Appointments are 30-45 minutes typically
- Please arrive 5 minutes early
- Carry any previous dental records if available
"""