import sqlite3
import os
import re
from datetime import datetime

DB_PATH = "bota.db"

# ============================================================
# PHONE VALIDATION — Indian 10-digit numbers only
# ============================================================
def is_valid_indian_phone(phone):
    """Validates a 10-digit Indian mobile number starting with 6-9."""
    cleaned = re.sub(r'[\s\-\+()]', '', phone)
    # Strip leading 91 or 0 country/trunk prefix if present
    if cleaned.startswith("91") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    if cleaned.startswith("0") and len(cleaned) == 11:
        cleaned = cleaned[1:]
    return bool(re.fullmatch(r'[6-9]\d{9}', cleaned))

def clean_phone(phone):
    """Returns the clean 10-digit number."""
    cleaned = re.sub(r'[\s\-\+()]', '', phone)
    if cleaned.startswith("91") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    if cleaned.startswith("0") and len(cleaned) == 11:
        cleaned = cleaned[1:]
    return cleaned

# ============================================================
# INIT — creates table if not exists
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            service TEXT DEFAULT 'General Consultation',
            status TEXT DEFAULT 'confirmed',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migration safety: if upgrading from an older database without phone column
    cursor.execute("PRAGMA table_info(appointments)")
    columns = [row[1] for row in cursor.fetchall()]
    if "phone" not in columns:
        cursor.execute("ALTER TABLE appointments ADD COLUMN phone TEXT DEFAULT ''")

    conn.commit()
    conn.close()

# ============================================================
# CHECK DUPLICATE — same date + time already booked?
# ============================================================
def is_slot_taken(date, time):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM appointments WHERE LOWER(date)=LOWER(?) AND LOWER(time)=LOWER(?) AND status='confirmed'",
        (date.strip(), time.strip())
    )
    result = cursor.fetchone()
    conn.close()
    return result is not None

# ============================================================
# ADD APPOINTMENT
# ============================================================
def add_appointment(data):
    init_db()

    name = data.get("name", "").strip()
    age = data.get("age", "").strip()
    phone = data.get("phone", "").strip()
    date = data.get("date", "").strip()
    time = data.get("time", "").strip().upper()
    service = data.get("service", "General Consultation").strip()

    if not name or not date or not time:
        return None, "Missing required fields"

    if phone and not is_valid_indian_phone(phone):
        return None, "Please provide a valid 10-digit Indian phone number."

    if phone:
        phone = clean_phone(phone)

    if is_slot_taken(date, time):
        return None, f"Sorry, the slot on {date} at {time} is already booked. Please choose a different time."

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO appointments (name, age, phone, date, time, service) VALUES (?, ?, ?, ?, ?, ?)",
        (name, age, phone, date, time, service)
    )
    conn.commit()
    appointment_id = cursor.lastrowid
    conn.close()

    return {
        "id": appointment_id,
        "name": name,
        "age": age,
        "phone": phone,
        "date": date,
        "time": time,
        "service": service,
        "status": "confirmed"
    }, None

# ============================================================
# GET ALL APPOINTMENTS
# ============================================================
def get_appointments():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM appointments ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ============================================================
# DELETE APPOINTMENT
# ============================================================
def delete_appointment(appointment_id):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE appointments SET status='cancelled' WHERE id=?", (appointment_id,))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0