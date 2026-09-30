import sqlite3
from datetime import datetime


DATABASE_NAME = "kolpulse.db"


def get_connection():
    return sqlite3.connect(DATABASE_NAME)


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

def init_database():

    conn = get_connection()
    cursor = conn.cursor()

    # Calls table
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

    # Verified KOL channels
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verified_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_username TEXT UNIQUE NOT NULL,
            user_id INTEGER,
            verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# VERIFIED CHANNELS
# =========================================================

def normalize_channel_username(channel_username):

    channel_username = channel_username.strip()

    if "t.me/" in channel_username:

        channel_username = channel_username.split(
            "t.me/",
            1
        )[1]

        channel_username = channel_username.split(
            "?",
            1
        )[0]

        channel_username = channel_username.split(
            "/",
            1
        )[0]

    channel_username = channel_username.lstrip("@")

    return channel_username.lower()


def add_verified_channel(
    channel_username,
    user_id=None
):

    channel_username = normalize_channel_username(
        channel_username
    )

    conn = get_connection()
    cursor = conn.cursor()

    verified_at = datetime.utcnow().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    cursor.execute("""
        INSERT OR REPLACE INTO verified_channels (
            channel_username,
            user_id,
            verified_at
        )
        VALUES (?, ?, ?)
    """, (
        channel_username,
        user_id,
        verified_at,
    ))

    conn.commit()
    conn.close()

    return verified_at


def get_verified_channel(channel_username):

    channel_username = normalize_channel_username(
        channel_username
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            channel_username,
            user_id,
            verified_at
        FROM verified_channels
        WHERE channel_username = ?
    """, (
        channel_username,
    ))

    result = cursor.fetchone()

    conn.close()

    return result


def get_verified_at(channel_username):

    result = get_verified_channel(
        channel_username
    )

    if not result:
        return None

    return result[3]


# =========================================================
# CALLS
# =========================================================

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


# =========================================================
# SEARCH KOL CALLS
# =========================================================

def get_calls_for_kol_after_verification(
    kol_username,
    verified_at
):

    kol_username = normalize_channel_username(
        kol_username
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM calls
        WHERE LOWER(
            REPLACE(kol_username, '@', '')
        ) = ?
        AND created_at >= ?
        ORDER BY created_at DESC
    """, (
        kol_username,
        verified_at,
    ))

    calls = cursor.fetchall()

    conn.close()

    return calls


# =========================================================
# UPDATE CALL MULTIPLIER
# =========================================================

def update_call_multiplier(
    call_id,
    current_mc,
    multiplier
):

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
