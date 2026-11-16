import sqlite3
import os
import re
from datetime import datetime

def normalize_date(date):
    date = date.strip()

    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
        try:
            parsed = datetime.strptime(date, fmt)
            return f"{parsed.day} {parsed.strftime('%B')} {parsed.year}"
        except ValueError:
            continue

    return date

def normalize_time(time):
    time = time.strip().upper()
    time = re.sub(r'\s+', ' ', time)

    # Normalize 10AM → 10 AM
    time = re.sub(r'(\d)(AM|PM)$', r'\1 \2', time)

    # Normalize 10:00AM → 10:00 AM
    time = re.sub(r'(\d{1,2}:\d{2})(AM|PM)$', r'\1 \2', time)

    for fmt in ("%I:%M %p", "%I %p", "%H:%M", "%H"):
        try:
            parsed = datetime.strptime(time, fmt)
            return parsed.strftime("%I:%M %p").lstrip("0")
        except ValueError:
            continue

    return time

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SQLITE_DB_PATH = os.path.join(os.path.dirname(__file__), "bota.db")


def is_postgres():
    return bool(DATABASE_URL)


def get_connection():
    if DATABASE_URL:
        import psycopg

        conn_string = DATABASE_URL
        if "sslmode=" not in conn_string:
            conn_string += "&sslmode=require" if "?" in conn_string else "?sslmode=require"

        # prepare_threshold=None avoids server-side prepared statements,
        # which is required when using Supabase transaction pooling.
        return psycopg.connect(
            conn_string,
            prepare_threshold=None,
            connect_timeout=10,
        )

    return sqlite3.connect(SQLITE_DB_PATH, timeout=10)


def is_valid_indian_phone(phone):
    cleaned = re.sub(r'[\s\-\+()]', '', phone)
    if cleaned.startswith("91") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    if cleaned.startswith("0") and len(cleaned) == 11:
        cleaned = cleaned[1:]
    return bool(re.fullmatch(r'[6-9]\d{9}', cleaned))


def clean_phone(phone):
    cleaned = re.sub(r'[\s\-\+()]', '', phone)
    if cleaned.startswith("91") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    if cleaned.startswith("0") and len(cleaned) == 11:
        cleaned = cleaned[1:]
    return cleaned


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    if is_postgres():
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                age TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                service TEXT DEFAULT 'General Consultation',
                status TEXT DEFAULT 'confirmed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
    else:
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

        cursor.execute("PRAGMA table_info(appointments)")
        columns = [row[1] for row in cursor.fetchall()]
        if "phone" not in columns:
            cursor.execute("ALTER TABLE appointments ADD COLUMN phone TEXT DEFAULT ''")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = get_connection()
    cursor = conn.cursor()

    if is_postgres():
        cursor.execute("SELECT value FROM settings WHERE key=%s", (key,))
    else:
        cursor.execute("SELECT value FROM settings WHERE key=?", (key,))

    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default


def set_setting(key, value):
    conn = get_connection()
    cursor = conn.cursor()

    if is_postgres():
        cursor.execute("""
            INSERT INTO settings (key, value)
            VALUES (%s, %s)
            ON CONFLICT(key)
            DO UPDATE SET value = EXCLUDED.value
        """, (key, value))
    else:
        cursor.execute("""
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value=excluded.value
        """, (key, value))

    conn.commit()
    conn.close()

def is_slot_taken(date, time):
    normalized_time = normalize_time(time)

    conn = get_connection()
    cursor = conn.cursor()

    if is_postgres():
        cursor.execute(
            """
            SELECT time
            FROM appointments
            WHERE LOWER(date) = LOWER(%s)
            AND status = 'confirmed'
            """,
            (date.strip(),)
        )
    else:
        cursor.execute(
            """
            SELECT time
            FROM appointments
            WHERE LOWER(date) = LOWER(?)
            AND status = 'confirmed'
            """,
            (date.strip(),)
        )

    rows = cursor.fetchall()
    conn.close()

    for row in rows:
        if normalize_time(str(row[0])) == normalized_time:
            return True

    return False

def add_appointment(data):

    name = data.get("name", "").strip()
    age = data.get("age", "").strip()
    phone = data.get("phone", "").strip()
    date = normalize_date(data.get("date", ""))
    time = normalize_time(data.get("time", ""))
    service = data.get("service", "General Consultation").strip()

    if not name or not date or not time:
        return None, "Missing required fields"

    if phone and not is_valid_indian_phone(phone):
        return None, "Please provide a valid 10-digit Indian phone number."

    if phone:
        phone = clean_phone(phone)

    if is_slot_taken(date, time):
        return None, (
            f"Sorry, the slot on {date} at {time} "
            "is already booked. Please choose a different time."
        )

    conn = get_connection()
    cursor = conn.cursor()

    if is_postgres():
        cursor.execute("""
            INSERT INTO appointments
            (name, age, phone, date, time, service)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (name, age, phone, date, time, service))
        appointment_id = cursor.fetchone()[0]
    else:
        cursor.execute("""
            INSERT INTO appointments
            (name, age, phone, date, time, service)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name, age, phone, date, time, service))
        appointment_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return {
        "id": appointment_id,
        "name": name,
        "age": age,
        "phone": phone,
        "date": date,
        "time": time,
        "service": service,
        "status": "confirmed",
    }, None


def get_appointments():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, age, phone, date, time, service, status, created_at
        FROM appointments
        ORDER BY created_at DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "id": row[0],
            "name": row[1],
            "age": row[2],
            "phone": row[3],
            "date": row[4],
            "time": row[5],
            "service": row[6],
            "status": row[7],
            "created_at": str(row[8]),
        }
        for row in rows
    ]


def delete_appointment(appointment_id):
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    if is_postgres():
        cursor.execute("""
            UPDATE appointments
            SET status='cancelled'
            WHERE id=%s
        """, (appointment_id,))
    else:
        cursor.execute("""
            UPDATE appointments
            SET status='cancelled'
            WHERE id=?
        """, (appointment_id,))

    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0

def permanently_delete_appointment(appointment_id):
    conn = get_connection()
    cursor = conn.cursor()

    if is_postgres():
        cursor.execute("""
            DELETE FROM appointments
            WHERE id=%s
        """, (appointment_id,))
    else:
        cursor.execute("""
            DELETE FROM appointments
            WHERE id=?
        """, (appointment_id,))

    conn.commit()
    affected = cursor.rowcount
    conn.close()

    return affected > 0

def get_available_slots(date):
    conn = get_connection()
    cursor = conn.cursor()

    if is_postgres():
        cursor.execute(
            """
            SELECT time
            FROM appointments
            WHERE LOWER(date) = LOWER(%s)
            AND status = 'confirmed'
            """,
            (date.strip(),)
        )
    else:
        cursor.execute(
            """
            SELECT time
            FROM appointments
            WHERE LOWER(date) = LOWER(?)
            AND status = 'confirmed'
            """,
            (date.strip(),)
        )

    rows = cursor.fetchall()
    conn.close()

    booked_times = {
        normalize_time(str(row[0]))
        for row in rows
    }

    available_slots = []

    # 10:00 AM → 12:30 PM
    for hour in range(10, 13):
        for minute in (0, 30):
            slot = f"{hour:02d}:{minute:02d}"

            formatted_slot = datetime.strptime(
                slot, "%H:%M"
            ).strftime("%I:%M %p").lstrip("0")

            if formatted_slot not in booked_times:
                available_slots.append(formatted_slot)

    # 2:00 PM → 8:00 PM
    for hour in range(14, 21):
        for minute in (0, 30):
            slot = f"{hour:02d}:{minute:02d}"

            formatted_slot = datetime.strptime(
                slot, "%H:%M"
            ).strftime("%I:%M %p").lstrip("0")

            if formatted_slot not in booked_times:
                available_slots.append(formatted_slot)

    return available_slots


# ============================================================
# MULTI-CLINIC DATABASE FUNCTIONS
# Existing functions above are preserved for backward compatibility.
# ============================================================

import json


def _require_postgres():
    if not is_postgres():
        raise RuntimeError(
            "Multi-clinic functionality requires the Supabase PostgreSQL database."
        )


def _json_value(value):
    """Convert a PostgreSQL JSON/JSONB value into a Python object."""
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value


# ------------------------------------------------------------
# CLINIC LOOKUP
# ------------------------------------------------------------

def get_clinic_by_id(clinic_id):
    _require_postgres()

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, slug, status
            FROM clinics
            WHERE id = %s
            LIMIT 1
        """, (clinic_id,))

        row = cursor.fetchone()

        if not row:
            return None

        return {
            "id": row[0],
            "name": row[1],
            "slug": row[2],
            "status": row[3],
        }
    finally:
        conn.close()


def get_clinic_by_slug(slug):
    _require_postgres()

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, slug, status
            FROM clinics
            WHERE LOWER(slug) = LOWER(%s)
            LIMIT 1
        """, (slug.strip(),))

        row = cursor.fetchone()

        if not row:
            return None

        return {
            "id": row[0],
            "name": row[1],
            "slug": row[2],
            "status": row[3],
        }
    finally:
        conn.close()


def get_active_clinic_by_slug(slug):
    clinic = get_clinic_by_slug(slug)

    if not clinic or clinic["status"] != "active":
        return None

    return clinic


# ------------------------------------------------------------
# CLINIC SETTINGS
# ------------------------------------------------------------

def get_clinic_settings(clinic_id):
    _require_postgres()

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT settings
            FROM clinic_settings
            WHERE clinic_id = %s
            LIMIT 1
        """, (clinic_id,))

        row = cursor.fetchone()

        return _json_value(row[0]) if row else {}
    finally:
        conn.close()


def save_clinic_settings(clinic_id, settings):
    _require_postgres()

    if not isinstance(settings, dict):
        raise ValueError("Settings must be a dictionary.")

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO clinic_settings (clinic_id, settings)
            VALUES (%s, %s::jsonb)
            ON CONFLICT (clinic_id)
            DO UPDATE SET settings = EXCLUDED.settings
        """, (clinic_id, json.dumps(settings)))

        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ------------------------------------------------------------
# CHATBOT CONFIGURATION
# ------------------------------------------------------------

def get_chatbot_config(clinic_id):
    _require_postgres()

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT config, is_enabled
            FROM chatbot_configs
            WHERE clinic_id = %s
            LIMIT 1
        """, (clinic_id,))

        row = cursor.fetchone()

        if not row:
            return {
                "config": {},
                "is_enabled": False,
            }

        return {
            "config": _json_value(row[0]),
            "is_enabled": bool(row[1]),
        }
    finally:
        conn.close()


def save_chatbot_config(clinic_id, config, is_enabled=True):
    _require_postgres()

    if not isinstance(config, dict):
        raise ValueError("Chatbot config must be a dictionary.")

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO chatbot_configs (clinic_id, config, is_enabled)
            VALUES (%s, %s::jsonb, %s)
            ON CONFLICT (clinic_id)
            DO UPDATE SET
                config = EXCLUDED.config,
                is_enabled = EXCLUDED.is_enabled
        """, (clinic_id, json.dumps(config), is_enabled))

        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ------------------------------------------------------------
# CLINIC-SPECIFIC APPOINTMENTS
# ------------------------------------------------------------

def is_slot_taken_for_clinic(clinic_id, date, time):
    _require_postgres()

    normalized_date = normalize_date(date)
    normalized_time = normalize_time(time)

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT time
            FROM appointments
            WHERE clinic_id = %s
              AND LOWER(date) = LOWER(%s)
              AND status = 'confirmed'
        """, (clinic_id, normalized_date))

        rows = cursor.fetchall()

        return any(
            normalize_time(str(row[0])) == normalized_time
            for row in rows
        )
    finally:
        conn.close()


def add_appointment_for_clinic(data, clinic_id):
    _require_postgres()

    name = str(data.get("name") or "").strip()
    age = str(data.get("age") or "").strip()
    phone = str(data.get("phone") or "").strip()
    date = normalize_date(str(data.get("date") or ""))
    time = normalize_time(str(data.get("time") or ""))
    service = str(
        data.get("service") or "General Consultation"
    ).strip()
    doctor_id = data.get("doctor_id")

    if not name or not date or not time:
        return None, "Missing required fields"

    if phone and not is_valid_indian_phone(phone):
        return None, "Please provide a valid 10-digit Indian phone number."

    if phone:
        phone = clean_phone(phone)

    clinic = get_clinic_by_id(clinic_id)

    if not clinic or clinic["status"] != "active":
        return None, "Clinic not found or inactive."

    conn = get_connection()
    try:
        cursor = conn.cursor()

        # Recheck the slot using this clinic's appointments only.
        cursor.execute("""
            SELECT time
            FROM appointments
            WHERE clinic_id = %s
              AND LOWER(date) = LOWER(%s)
              AND status = 'confirmed'
        """, (clinic_id, date))

        rows = cursor.fetchall()

        if any(
            normalize_time(str(row[0])) == time
            for row in rows
        ):
            return None, (
                f"Sorry, the slot on {date} at {time} "
                "is already booked. Please choose another time."
            )

        cursor.execute("""
            INSERT INTO appointments
                (clinic_id, doctor_id, name, age, phone,
                 date, time, service, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'confirmed')
            RETURNING id
        """, (
            clinic_id, doctor_id, name, age, phone,
            date, time, service
        ))

        appointment_id = cursor.fetchone()[0]
        conn.commit()

        return {
            "id": appointment_id,
            "clinic_id": clinic_id,
            "doctor_id": doctor_id,
            "name": name,
            "age": age,
            "phone": phone,
            "date": date,
            "time": time,
            "service": service,
            "status": "confirmed",
        }, None

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_appointments_for_clinic(clinic_id):
    _require_postgres()

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, age, phone, date, time,
                   service, status, created_at, doctor_id
            FROM appointments
            WHERE clinic_id = %s
            ORDER BY created_at DESC
        """, (clinic_id,))

        rows = cursor.fetchall()

        return [
            {
                "id": row[0],
                "name": row[1],
                "age": row[2],
                "phone": row[3],
                "date": row[4],
                "time": row[5],
                "service": row[6],
                "status": row[7],
                "created_at": str(row[8]),
                "doctor_id": row[9],
                "clinic_id": clinic_id,
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_available_slots_for_clinic(clinic_id, date):
    _require_postgres()

    normalized_date = normalize_date(date)

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT time
            FROM appointments
            WHERE clinic_id = %s
              AND LOWER(date) = LOWER(%s)
              AND status = 'confirmed'
        """, (clinic_id, normalized_date))

        rows = cursor.fetchall()

        booked_times = {
            normalize_time(str(row[0]))
            for row in rows
        }

    finally:
        conn.close()

    available_slots = []

    for hour in range(10, 13):
        for minute in (0, 30):
            slot = f"{hour:02d}:{minute:02d}"
            formatted = datetime.strptime(
                slot, "%H:%M"
            ).strftime("%I:%M %p").lstrip("0")

            if formatted not in booked_times:
                available_slots.append(formatted)

    for hour in range(14, 21):
        for minute in (0, 30):
            slot = f"{hour:02d}:{minute:02d}"
            formatted = datetime.strptime(
                slot, "%H:%M"
            ).strftime("%I:%M %p").lstrip("0")

            if formatted not in booked_times:
                available_slots.append(formatted)

    return available_slots


def cancel_appointment_for_clinic(appointment_id, clinic_id):
    _require_postgres()

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE appointments
            SET status = 'cancelled'
            WHERE id = %s AND clinic_id = %s
        """, (appointment_id, clinic_id))

        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def permanently_delete_appointment_for_clinic(
    appointment_id, clinic_id
):
    _require_postgres()

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM appointments
            WHERE id = %s AND clinic_id = %s
        """, (appointment_id, clinic_id))

        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# MULTI-CLINIC DOCTOR MANAGEMENT
# ============================================================

def get_doctors_for_clinic(clinic_id, active_only=False):
    _require_postgres()

    conn = get_connection()
    try:
        cursor = conn.cursor()

        query = """
            SELECT id, clinic_id, name, qualification,
                   specialization, experience, is_active, created_at
            FROM doctors
            WHERE clinic_id = %s
        """

        if active_only:
            query += " AND is_active = TRUE"

        query += " ORDER BY name ASC"

        cursor.execute(query, (clinic_id,))
        rows = cursor.fetchall()

        return [
            {
                "id": row[0],
                "clinic_id": row[1],
                "name": row[2],
                "qualification": row[3],
                "specialization": row[4],
                "experience": row[5],
                "is_active": row[6],
                "created_at": str(row[7]),
            }
            for row in rows
        ]
    finally:
        conn.close()


def add_doctor_for_clinic(
    clinic_id,
    name,
    qualification="",
    specialization="",
    experience=""
):
    _require_postgres()

    name = str(name or "").strip()

    if not name:
        return None, "Doctor name is required."

    clinic = get_clinic_by_id(clinic_id)

    if not clinic or clinic["status"] != "active":
        return None, "Clinic not found or inactive."

    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO doctors (
                clinic_id, name, qualification,
                specialization, experience, is_active
            )
            VALUES (%s, %s, %s, %s, %s, TRUE)
            RETURNING id, clinic_id, name, qualification,
                      specialization, experience, is_active, created_at
        """, (
            clinic_id,
            name,
            str(qualification or "").strip(),
            str(specialization or "").strip(),
            str(experience or "").strip(),
        ))

        row = cursor.fetchone()
        conn.commit()

        return {
            "id": row[0],
            "clinic_id": row[1],
            "name": row[2],
            "qualification": row[3],
            "specialization": row[4],
            "experience": row[5],
            "is_active": row[6],
            "created_at": str(row[7]),
        }, None

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_doctor_for_clinic(
    doctor_id,
    clinic_id,
    name,
    qualification="",
    specialization="",
    experience=""
):
    _require_postgres()

    name = str(name or "").strip()

    if not name:
        return False, "Doctor name is required."

    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE doctors
            SET name = %s,
                qualification = %s,
                specialization = %s,
                experience = %s
            WHERE id = %s AND clinic_id = %s
        """, (
            name,
            str(qualification or "").strip(),
            str(specialization or "").strip(),
            str(experience or "").strip(),
            doctor_id,
            clinic_id,
        ))

        updated = cursor.rowcount > 0
        conn.commit()

        return updated, None if updated else "Doctor not found."

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_doctor_active_for_clinic(
    doctor_id,
    clinic_id,
    is_active
):
    _require_postgres()

    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE doctors
            SET is_active = %s
            WHERE id = %s AND clinic_id = %s
        """, (bool(is_active), doctor_id, clinic_id))

        updated = cursor.rowcount > 0
        conn.commit()

        return updated

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()




def get_all_clinics():
    """Return all clinics with their saved settings."""
    _require_postgres()

    conn = get_connection()
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT
                c.id,
                c.name,
                c.slug,
                c.status,
                COALESCE(cs.settings->>'clinic_type', '') AS type,
                COALESCE(cs.settings->>'address', '') AS address,
                COALESCE(cs.settings->>'phone', '') AS phone,
                COALESCE(cs.settings->>'email', '') AS email,
                COALESCE(cs.settings->>'website', '') AS website
            FROM clinics c
            LEFT JOIN clinic_settings cs
                ON cs.clinic_id = c.id
            ORDER BY c.id DESC
        """)

        rows = cur.fetchall()
        columns = [col[0] for col in cur.description]

        return [
            dict(zip(columns, row))
            for row in rows
        ]

    finally:
        conn.close()




def create_clinic(
    name,
    clinic_type="",
    address="",
    phone="",
    email="",
    website="",
    status="active"
):
    """Create a clinic and initialize its settings and chatbot configuration."""
    _require_postgres()

    import re
    import json

    name = str(name).strip()
    if not name:
        raise ValueError("Clinic name is required.")

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    if not slug:
        raise ValueError("Could not generate a valid clinic URL.")

    status = str(status).strip().lower()
    if status not in ("active", "inactive"):
        raise ValueError("Status must be active or inactive.")

    settings = {
    "clinic_name": name,
    "clinic_type": clinic_type,
    "address": address,
    "phone": phone,
    "email": email,
    "website": website,

    "weekday_hours": "Monday to Saturday: 9:00 AM to 8:00 PM",
    "sunday_hours": "Sunday: 10:00 AM to 2:00 PM",

    "open_hour": 9,
    "close_hour": 20,

    "services": [],
    "payment": "Cash, UPI, All major cards accepted",
    "parking": "Available"
}

    conn = get_connection()

    try:
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO clinics (name, slug, status)
            VALUES (%s, %s, %s)
            RETURNING id, name, slug, status
        """, (name, slug, status))

        row = cur.fetchone()
        columns = [col[0] for col in cur.description]
        clinic = dict(zip(columns, row))

        clinic_id = clinic["id"]

        cur.execute("""
            INSERT INTO clinic_settings (clinic_id, settings)
            VALUES (%s, %s::jsonb)
            ON CONFLICT (clinic_id)
            DO UPDATE SET settings = EXCLUDED.settings
        """, (clinic_id, json.dumps(settings)))

        cur.execute("""
            INSERT INTO chatbot_configs (clinic_id, config, is_enabled)
            VALUES (%s, %s::jsonb, TRUE)
            ON CONFLICT (clinic_id) DO NOTHING
        """, (clinic_id, json.dumps({})))

        conn.commit()
        return clinic

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def update_clinic_status(clinic_id, status):
    """Activate or deactivate a clinic."""
    _require_postgres()

    status = str(status).strip().lower()
    if status not in ("active", "inactive"):
        raise ValueError("Invalid clinic status.")

    conn = get_connection()

    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE clinics
            SET status = %s
            WHERE id = %s
            RETURNING id, name, slug, status
        """, (status, clinic_id))

        row = cur.fetchone()

        if not row:
            conn.rollback()
            return None

        columns = [col[0] for col in cur.description]
        result = dict(zip(columns, row))

        conn.commit()
        return result

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()
