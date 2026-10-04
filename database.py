import sqlite3
from datetime import datetime, timedelta


# Persistent SQLite database file used by KOLPulse.
# The GitHub Actions workflow restores/saves this file between runs.
DATABASE_NAME = "kolpulse.db"


def get_connection():
    return sqlite3.connect(DATABASE_NAME, timeout=30)


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

def init_database():

    conn = get_connection()
    cursor = conn.cursor()

    # =====================================================
    # CALLS
    # =====================================================

    cursor.execute(""" CREATE TABLE IF NOT EXISTS calls ( id INTEGER PRIMARY KEY AUTOINCREMENT, kol_username TEXT NOT NULL, kol_link TEXT, project_name TEXT NOT NULL, project_link TEXT, original_call_link TEXT, call_mc REAL, current_mc REAL, multiplier REAL DEFAULT 0, call_time TEXT, video_file_id TEXT, status TEXT DEFAULT 'live', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ) """)

    # =====================================================
    # VERIFIED CHANNELS
    # =====================================================

    cursor.execute(""" CREATE TABLE IF NOT EXISTS verified_channels ( id INTEGER PRIMARY KEY AUTOINCREMENT, channel_username TEXT UNIQUE NOT NULL, user_id INTEGER, verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ) """)

    # =====================================================
    # PENDING CHANNEL REQUESTS
    # =====================================================

    cursor.execute(""" CREATE TABLE IF NOT EXISTS channel_requests ( id INTEGER PRIMARY KEY AUTOINCREMENT, channel_username TEXT UNIQUE NOT NULL, user_id INTEGER, status TEXT DEFAULT 'pending', submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ) """)

    # Archived verification records are kept permanently so removing an old
    # active verification never removes the channel's historical data.
    cursor.execute(""" CREATE TABLE IF NOT EXISTS verified_channels_archive ( id INTEGER PRIMARY KEY, channel_username TEXT NOT NULL, user_id INTEGER, verified_at TIMESTAMP, archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ) """)

    conn.commit()
    conn.close()


# =========================================================
# NORMALIZE CHANNEL USERNAME
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


# =========================================================
# VERIFIED CHANNELS
# =========================================================

def add_verified_channel( channel_username, user_id=None ):

    channel_username = normalize_channel_username(
        channel_username
    )

    conn = get_connection()
    cursor = conn.cursor()

    verified_at = datetime.utcnow().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    cursor.execute(""" INSERT OR REPLACE INTO verified_channels ( channel_username, user_id, verified_at ) VALUES (?, ?, ?) """, (
        channel_username,
        user_id,
        verified_at,
    ))

    # Remove pending request after approval
    cursor.execute(""" DELETE FROM channel_requests WHERE channel_username = ? """, (
        channel_username,
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

    cursor.execute(""" SELECT id, channel_username, user_id, verified_at FROM verified_channels WHERE channel_username = ? """, (
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
# PENDING REQUESTS
# =========================================================

def add_pending_channel( channel_username, user_id=None ):

    channel_username = normalize_channel_username(
        channel_username
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(""" INSERT OR IGNORE INTO channel_requests ( channel_username, user_id, status ) VALUES (?, ?, 'pending') """, (
        channel_username,
        user_id,
    ))

    conn.commit()
    conn.close()


def get_pending_channel(channel_username):

    channel_username = normalize_channel_username(
        channel_username
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(""" SELECT id, channel_username, user_id, status, submitted_at FROM channel_requests WHERE channel_username = ? AND status = 'pending' """, (
        channel_username,
    ))

    result = cursor.fetchone()

    conn.close()

    return result


def remove_pending_channel(channel_username):

    channel_username = normalize_channel_username(
        channel_username
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(""" DELETE FROM channel_requests WHERE channel_username = ? """, (
        channel_username,
    ))

    conn.commit()
    conn.close()


# =========================================================
# CALLS
# =========================================================

def add_call( kol_username, project_name, kol_link=None, project_link=None, original_call_link=None, call_mc=None, current_mc=None, multiplier=0, call_time=None, video_file_id=None, status="live", ):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(""" INSERT INTO calls ( kol_username, kol_link, project_name, project_link, original_call_link, call_mc, current_mc, multiplier, call_time, video_file_id, status ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) """, (
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

    cursor.execute(""" SELECT * FROM calls WHERE status = 'live' ORDER BY created_at DESC """)

    calls = cursor.fetchall()

    conn.close()

    return calls


# =========================================================
# SEARCH KOL CALLS
# =========================================================

def get_calls_for_kol_after_verification( kol_username, verified_at ):

    kol_username = normalize_channel_username(
        kol_username
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(""" SELECT * FROM calls WHERE LOWER( REPLACE(kol_username, '@', '') ) = ? AND created_at >= ? ORDER BY created_at DESC """, (
        kol_username,
        verified_at,
    ))

    calls = cursor.fetchall()

    conn.close()

    return calls


# =========================================================
# UPDATE CALL MULTIPLIER
# =========================================================

def update_call_multiplier( call_id, current_mc, multiplier ):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(""" UPDATE calls SET current_mc = ?, multiplier = ? WHERE id = ? """, (
        current_mc,
        multiplier,
        call_id,
    ))

    conn.commit()
    conn.close()

def is_verified_channel(channel_username):
    """Return True when the channel is already present in verified_channels."""
    return get_verified_channel(channel_username) is not None


def get_all_verified_channels():
    """Return all currently verified channel usernames."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT channel_username FROM verified_channels "
            "ORDER BY verified_at ASC"
        )
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


# =========================================================
# VERIFIED CHANNEL RETENTION
# =========================================================

VERIFIED_CHANNEL_RETENTION_DAYS = 30

def cleanup_expired_verified_channels(retention_days=VERIFIED_CHANNEL_RETENTION_DAYS):
    """
    Remove active verified-channel entries only after the full retention
    period has passed. Historical channel data is archived first.

    IMPORTANT: This function NEVER deletes calls, milestones, videos,
    projects, or any other tracking data. It only removes the active
    verification entry after 30 days.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cutoff = datetime.utcnow() - timedelta(days=int(retention_days))
        cutoff_text = cutoff.strftime("%Y-%m-%d %H:%M:%S")

        cur.execute(
            """SELECT id, channel_username, user_id, verified_at
               FROM verified_channels
               WHERE verified_at IS NOT NULL AND verified_at <= ?""",
            (cutoff_text,),
        )
        expired = cur.fetchall()

        if not expired:
            return 0

        for row in expired:
            channel_id, channel_username, user_id, verified_at = row
            cur.execute(
                """INSERT OR IGNORE INTO verified_channels_archive
                   (id, channel_username, user_id, verified_at, archived_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (channel_id, channel_username, user_id, verified_at),
            )

        ids = [row[0] for row in expired]
        cur.executemany(
            "DELETE FROM verified_channels WHERE id = ?",
            [(channel_id,) for channel_id in ids],
        )

        conn.commit()
        print(
            f"🧹 Archived {len(expired)} verified channel(s) older than "
            f"{int(retention_days)} days. Calls and tracking data were kept."
        )
        return len(expired)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
       
 
