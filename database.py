import os
import re
import sqlite3

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
    conn = get_connection()
    cursor = conn.cursor()

    if is_postgres():
        cursor.execute("""
            SELECT id
            FROM appointments
            WHERE LOWER(date)=LOWER(%s)
              AND LOWER(time)=LOWER(%s)
              AND status='confirmed'
        """, (date.strip(), time.strip()))
    else:
        cursor.execute("""
            SELECT id
            FROM appointments
            WHERE LOWER(date)=LOWER(?)
              AND LOWER(time)=LOWER(?)
              AND status='confirmed'
        """, (date.strip(), time.strip()))

    result = cursor.fetchone()
    conn.close()
    return result is not None


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
    init_db()
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
