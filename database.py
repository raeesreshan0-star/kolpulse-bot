import sqlite3

DATABASE_NAME = "kolpulse.db"


def get_connection():
    return sqlite3.connect(DATABASE_NAME)


def init_database():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kol_username TEXT NOT NULL,
            kol_link TEXT,
            project_name TEXT NOT NULL,
            project_link TEXT,
            original_call_link TEXT,
            call_mc REAL,
            current_mc REAL,
            multiplier REAL DEFAULT 0,
            call_time TEXT,
            video_file_id TEXT,
            status TEXT DEFAULT 'live',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def add_call(
    kol_username,
    project_name,
    kol_link=None,
    project_link=None,
    original_call_link=None,
    call_mc=None,
    current_mc=None,
    multiplier=0,
    call_time=None,
    video_file_id=None,
    status="live",
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO calls (
            kol_username,
            kol_link,
            project_name,
            project_link,
            original_call_link,
            call_mc,
            current_mc,
            multiplier,
            call_time,
            video_file_id,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        kol_username,
        kol_link,
        project_name,
        project_link,
        original_call_link,
        call_mc,
        current_mc,
        multiplier,
        call_time,
        video_file_id,
        status,
    ))

    conn.commit()
    call_id = cursor.lastrowid
    conn.close()

    return call_id


def get_live_calls():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM calls
        WHERE status = 'live'
        ORDER BY created_at DESC
    """)

    calls = cursor.fetchall()
    conn.close()

    return calls


def update_call_multiplier(call_id, current_mc, multiplier):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE calls
        SET current_mc = ?,
            multiplier = ?
        WHERE id = ?
    """, (
        current_mc,
        multiplier,
        call_id,
    ))

    conn.commit()
    conn.close()
