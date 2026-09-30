import os
import re
import html
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from database import (
    init_database,
    get_live_calls,
    add_call,
    add_verified_channel,
    get_verified_channel,
    get_calls_for_kol_after_verification,
    get_connection,
)


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "").strip()

LIVE_CHANNEL = "@KOLPulse_Live"
BOT_USERNAME = "@KOLPulse_Live_bot"
BOT_LINK = "https://t.me/KOLPulse_Live_bot"


# =========================================================
# CHANNEL REQUEST STATUS
# =========================================================

def normalize_channel(channel):

    channel = (channel or "").strip()

    if "t.me/" in channel.lower():

        channel = channel.split(
            "t.me/",
            1
        )[1]

        channel = channel.split(
            "?",
            1
        )[0]

        channel = channel.split(
            "/",
            1
        )[0]

    if not channel.startswith("@"):
        channel = "@" + channel

    return channel


def ensure_tracking_requests_table():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channel_tracking_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_username TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def get_request_status(channel):

    channel = normalize_channel(channel)
    clean = channel.lstrip("@").lower()

    try:

        verified = get_verified_channel(
            channel
        )

        if verified:
            return "approved"

    except Exception as error:

        print(
            "⚠️ get_verified_channel check failed: "
            f"{type(error).__name__}: {error}"
        )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT status
        FROM channel_tracking_requests
        WHERE LOWER(REPLACE(channel_username, '@', '')) = ?
        ORDER BY id DESC
        LIMIT 1
    """, (clean,))

    row = cursor.fetchone()

    conn.close()

    if not row:
        return None

    return row[0]


def save_pending_request(
    channel,
    user_id
):

    channel = normalize_channel(channel)

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, status
        FROM channel_tracking_requests
        WHERE LOWER(REPLACE(channel_username, '@', '')) = ?
        ORDER BY id DESC
        LIMIT 1
    """, (
        channel.lstrip("@").lower(),
    ))

    row = cursor.fetchone()

    if row:

        request_id, status = row

        if status == "pending":

            conn.close()

            return False

        cursor.execute("""
            UPDATE channel_tracking_requests
            SET user_id = ?,
                status = 'pending',
                updated_at = ?
            WHERE id = ?
        """, (
            user_id,
            now,
            request_id,
        ))

    else:

        cursor.execute("""
            INSERT INTO channel_tracking_requests
            (
                channel_username,
                user_id,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, 'pending', ?, ?)
        """, (
            channel,
            user_id,
            now,
            now,
        ))

    conn.commit()
    conn.close()

    return True


def update_request_status(
    channel,
    status
):

    channel = normalize_channel(channel)

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE channel_tracking_requests
        SET status = ?,
            updated_at = ?
        WHERE LOWER(REPLACE(channel_username, '@', '')) = ?
    """, (
        status,
        now,
        channel.lstrip("@").lower(),
    ))

    conn.commit()
    conn.close()


# =========================================================
# MAIN MENU
# ONLY 5 MAIN BUTTONS
# =========================================================

def main_menu():

    keyboard = [

        [
            InlineKeyboardButton(
                "📡 Track My Channel",
                callback_data="track_channel"
            )
        ],

        [
            InlineKeyboardButton(
                "📊 KOL Leaderboard",
                callback_data="leaderboard"
            )
        ],

        [
            InlineKeyboardButton(
                "🔎 Search KOL",
                callback_data="search_kol"
            )
        ],

        [
            InlineKeyboardButton(
                "🏆 Top KOLs",
                callback_data="top_kols"
            )
        ],

        [
            InlineKeyboardButton(
                "🆘 Support",
                callback_data="support"
            )
        ],
    ]

    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# ACCEPT / REJECT BUTTONS
# ADMIN WORKFLOW
# =========================================================

def request_buttons(
    user_id,
    channel
):

    channel_name = channel.lstrip("@")

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Accept",
                callback_data=(
                    f"accept:{user_id}:{channel_name}"
                )
            ),

            InlineKeyboardButton(
                "❌ Reject",
                callback_data=(
                    f"reject:{user_id}:{channel_name}"
                )
            ),
        ]
    ])


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data[
        "waiting_for_channel"
    ] = False

    context.user_data[
        "waiting_for_kol_search"
    ] = False

    context.user_data[
        "channel_admin_check"
    ] = False

    await update.message.reply_text(

        "⚡ Welcome to KOLPulse!\n\n"
        "Track Telegram KOL calls, "
        "leaderboards and KOL performance.\n\n"
        "Choose an option below:",

        reply_markup=main_menu(),
    )


# =========================================================
# GROUP ID
# =========================================================

async def groupid(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat = update.effective_chat

    await update.message.reply_text(

        "🆔 Chat ID:\n\n"
        f"`{chat.id}`",

        parse_mode="Markdown",
    )


# =========================================================
# MARKET CAP FORMAT
# =========================================================

def format_market_cap(value):

    if value is None:
        return "N/A"

    if value >= 1_000_000_000:
        return (
            f"${value / 1_000_000_000:.1f}B"
        )

    if value >= 1_000_000:
        return (
            f"${value / 1_000_000:.1f}M"
        )

    if value >= 1_000:
        return (
            f"${value / 1_000:.1f}K"
        )

    return f"${value:,.0f}"


# =========================================================
# TOKEN SYMBOL DETECTION
# =========================================================

def detect_token_symbol(
    text,
    project_name,
    contract
):

    source = text or ""

    # $TOKEN
    match = re.search(
        r"\$([A-Za-z][A-Za-z0-9_]*)",
        source
    )

    if match:

        return "$" + match.group(1)


    # Symbol: TOKEN
    symbol_patterns = [

        r"(?:token\s*symbol|symbol)"
        r"\s*[:=\-]\s*"
        r"\$?([A-Za-z][A-Za-z0-9_]*)",

        r"(?:ticker)"
        r"\s*[:=\-]\s*"
        r"\$?([A-Za-z][A-Za-z0-9_]*)",
    ]

    for pattern in symbol_patterns:

        match = re.search(
            pattern,
            source,
            re.IGNORECASE
        )

        if match:

            return "$" + match.group(1)


    # Try project name
    match = re.search(
        r"\$([A-Za-z][A-Za-z0-9_]*)",
        project_name or ""
    )

    if match:

        return "$" + match.group(1)


    # Do not use contract address as token symbol.
    return "$TOKEN"


# =========================================================
# CONTRACT / CA DETECTION
# =========================================================

def parse_contract(text):

    """
    Detects many common CA formats:

    Contract: 0x...
    Contract Address: 0x...
    CA: 0x...
    CA : 0x...
    CA - 0x...
    CA = 0x...

    Solana addresses
    EVM addresses
    General long CA strings
    """

    if not text:
        return None


    # =====================================================
    # EVM ADDRESS
    # =====================================================

    evm = re.search(
        r"\b0x[a-fA-F0-9]{40}\b",
        text
    )

    # Keep searching for explicit CA first,
    # but EVM fallback is always available.


    # =====================================================
    # EXPLICIT LABELS
    # =====================================================

    explicit_patterns = [

        r"(?:contract\s+address)"
        r"\s*[:=\-]?\s*"
        r"`?([A-Za-z0-9]{20,120})`?",

        r"(?:contract)"
        r"\s*[:=\-]?\s*"
        r"`?([A-Za-z0-9]{20,120})`?",

        r"(?:ca)"
        r"\s*[:=\-]?\s*"
        r"`?([A-Za-z0-9]{20,120})`?",
    ]


    for pattern in explicit_patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            value = match.group(1).strip()

            # Remove accidental punctuation
            value = value.strip(
                "`'\"<>[](){}.,; "
            )

            if len(value) >= 20:

                return value


    # =====================================================
    # EVM FALLBACK
    # =====================================================

    if evm:

        return evm.group(0)


    # =====================================================
    # SOLANA / GENERAL ADDRESS FALLBACK
    # =====================================================

    # Long Base58-style strings.
    # Avoid matching normal English words.

    candidates = re.findall(
        r"\b[A-HJ-NP-Za-km-z1-9]{32,64}\b",
        text
    )

    for candidate in candidates:

        # Skip obvious URLs / normal words
        if candidate.lower() in [
            "abcdefghijklmnopqrstuvwxyz",
            "abcdefghijklmnopqrstuvwxyz123456",
        ]:
            continue

        # Require a reasonable mixture
        has_letter = bool(
            re.search(
                r"[A-Za-z]",
                candidate
            )
        )

        has_number = bool(
            re.search(
                r"[0-9]",
                candidate
            )
        )

        if has_letter and has_number:

            return candidate


    return None


# =========================================================
# MARKET CAP / MC DETECTION
# =========================================================

def parse_market_cap(text):

    """
    Supports:

    Market Cap: $50K
    Market Cap $50K
    MC: $50K
    MC $50K
    Current MC: $52.5K
    Current Market Cap: $52.5K
    $30.8K MC
    $30.8K mc
    Current chart is $30.8K mc
    FDV: $1M
    """

    if not text:
        return None


    # =====================================================
    # EXPLICIT MC PATTERNS
    # =====================================================

    explicit_patterns = [

        r"(?:market\s*cap|marketcap)"
        r"\s*(?:is|:|=|-)?\s*"
        r"\$?\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*([KMB])?\b",

        r"(?:current\s+market\s*cap)"
        r"\s*(?:is|:|=|-)?\s*"
        r"\$?\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*([KMB])?\b",

        r"(?:current\s*mc)"
        r"\s*(?:is|:|=|-)?\s*"
        r"\$?\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*([KMB])?\b",

        r"(?:\bmc\b)"
        r"\s*(?:is|:|=|-)?\s*"
        r"\$?\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*([KMB])?\b",

        r"\$?\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*([KMB])?\s*"
        r"(?:mc|market\s*cap)\b",
    ]


    for pattern in explicit_patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            try:

                number = float(
                    match.group(1)
                )

            except ValueError:

                continue

            suffix = (
                match.group(2) or ""
            ).upper()

            if suffix == "K":

                number *= 1_000

            elif suffix == "M":

                number *= 1_000_000

            elif suffix == "B":

                number *= 1_000_000_000

            return number


    # =====================================================
    # CURRENT CHART
    # =====================================================

    chart_pattern = re.search(

        r"(?:current\s+chart|chart|"
        r"current\s+market\s+cap)"
        r".{0,80}?"
        r"\$?\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*([KMB])?\s*"
        r"mc\b",

        text,
        re.IGNORECASE
    )


    if chart_pattern:

        number = float(
            chart_pattern.group(1)
        )

        suffix = (
            chart_pattern.group(2) or ""
        ).upper()

        if suffix == "K":

            number *= 1_000

        elif suffix == "M":

            number *= 1_000_000

        elif suffix == "B":

            number *= 1_000_000_000

        return number


    # =====================================================
    # FDV / VALUATION FALLBACK
    # =====================================================

    fdv_pattern = re.search(

        r"(?:fdv|valuation)"
        r"\s*(?:is|:|=|-)?\s*"
        r"\$?\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*([KMB])?\b",

        text,
        re.IGNORECASE
    )


    if fdv_pattern:

        number = float(
            fdv_pattern.group(1)
        )

        suffix = (
            fdv_pattern.group(2) or ""
        ).upper()

        if suffix == "K":

            number *= 1_000

        elif suffix == "M":

            number *= 1_000_000

        elif suffix == "B":

            number *= 1_000_000_000

        return number


    # =====================================================
    # NO MC FOUND
    # =====================================================

    return None


# =========================================================
# PROJECT LINK DETECTION
# =========================================================

def parse_project_link(text):

    if not text:
        return None


    urls = re.findall(
        r"https?://[^\s<>()]+",
        text,
        re.IGNORECASE
    )


    for url in urls:

        url = url.rstrip(
            ".,;:!?)]}>\"'"
        )

        lower = url.lower()


        # Prefer project/social/chart links
        if (
            "x.com/" in lower
            or "twitter.com/" in lower
            or "dexscreener.com/" in lower
            or "pump.fun/" in lower
            or "birdeye.so/" in lower
            or "raydium.io/" in lower
            or "dextools.io/" in lower
        ):

            return url


    # If no preferred link,
    # return first valid URL.

    if urls:

        return urls[0].rstrip(
            ".,;:!?)]}>\"'"
        )


    return None


# =========================================================
# PROJECT NAME
# =========================================================

def parse_project_name(
    text,
    contract
):

    if not text:

        return (
            contract[:12]
            if contract
            else "Unknown Project"
        )


    # =====================================================
    # EXPLICIT PROJECT NAME
    # =====================================================

    for line in text.splitlines():

        clean = line.strip()

        if re.match(
            r"^(name|project\s*name|project)"
            r"\s*:",
            clean,
            re.IGNORECASE
        ):

            value = re.split(
                r":",
                clean,
                maxsplit=1
            )[1].strip()

            if value:

                return value


    # =====================================================
    # TOKEN / $ SYMBOL LINE
    # =====================================================

    for line in text.splitlines():

        clean = line.strip()

        if not clean:
            continue

        if re.search(
            r"\$[A-Za-z][A-Za-z0-9_]*",
            clean
        ):

            if not re.search(
                r"(?:CA|Contract|Market Cap|"
                r"Current MC|MC|Dexscreener|"
                r"Telegram|Twitter|X:|"
                r"FDV)\b",
                clean,
                re.IGNORECASE
            ):

                if len(clean) <= 120:

                    return clean


    # =====================================================
    # X/TWITTER HANDLE AS PROJECT NAME
    # =====================================================

    x_match = re.search(
        r"(?:x\.com|twitter\.com)/"
        r"([A-Za-z0-9_]+)",
        text,
        re.IGNORECASE
    )

    if x_match:

        handle = x_match.group(1)

        if handle:

            return handle


    # =====================================================
    # FIRST SHORT NON-URL LINE
    # =====================================================

    for line in text.splitlines():

        clean = line.strip()

        if not clean:
            continue

        if clean.startswith(
            ("http://", "https://")
        ):
            continue

        if re.fullmatch(
            r"0x[a-fA-F0-9]{40}",
            clean
        ):
            continue

        if re.match(
            r"^(CA|Contract|Contract Address|"
            r"MC|Market Cap|FDV)\b",
            clean,
            re.IGNORECASE
        ):
            continue

        if 2 <= len(clean) <= 100:

            # Avoid long Chinese/English descriptions
            # being used as project name.
            if len(clean.split()) <= 12:

                return clean


    # =====================================================
    # CONTRACT FALLBACK
    # =====================================================

    if contract:

        return contract[:12]


    return "Unknown Project"


# =========================================================
# CHAIN DETECTION
# =========================================================

def detect_chain_symbol(
    text,
    contract=None
):

    source = (
        text or ""
    ).lower()


    if (
        "solana" in source
        or "sol " in source
        or "sol:" in source
        or "dexscreener.com/solana/" in source
    ):

        return "SOL"


    if (
        "ethereum" in source
        or "eth " in source
        or "eth:" in source
        or "dexscreener.com/ethereum/" in source
    ):

        return "ETH"


    if (
        "base" in source
        or "base chain" in source
        or "dexscreener.com/base/" in source
    ):

        return "BASE"


    if (
        "bsc" in source
        or "bnb" in source
        or "binance smart chain" in source
        or "dexscreener.com/bsc/" in source
    ):

        return "BSC"


    if (
        "arbitrum" in source
        or "arb " in source
        or "arb:" in source
        or "dexscreener.com/arbitrum/" in source
    ):

        return "ARB"


    if (
        "polygon" in source
        or "matic" in source
        or "dexscreener.com/polygon/" in source
    ):

        return "POLY"


    if (
        "avalanche" in source
        or "avax" in source
        or "dexscreener.com/avalanche/" in source
    ):

        return "AVAX"


    # EVM address alone does not tell us which EVM chain.
    if contract and re.fullmatch(
        r"0x[a-fA-F0-9]{40}",
        contract
    ):

        return "EVM"


    return "UNKNOWN"


# =========================================================
# VERIFIED CHANNEL CHECK
# =========================================================

def is_verified_channel(channel):

    channel = normalize_channel(
        channel
    )

    try:

        verified = get_verified_channel(
            channel
        )

        if verified:

            return True

    except Exception as error:

        print(
            "❌ Verification database error for "
            f"{channel}: "
            f"{type(error).__name__}: {error}"
        )

    return False


# =========================================================
# LIVE CALLS
# =========================================================

async def show_live_calls(query):

    calls = get_live_calls()

    if not calls:

        await query.edit_message_text(

            "🔥 Live Calls\n\n"
            "No live calls are available yet.",

            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data="back_menu"
                    )
                ]
            ]),
        )

        return


    text = "🔥 LIVE CALLS\n\n"


    for call in calls[:10]:

        (
            call_id,
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
            created_at,
        ) = call


        call_mc_text = (

            f"${call_mc:,.0f}"

            if call_mc is not None

            else "N/A"
        )


        current_mc_text = (

            f"${current_mc:,.0f}"

            if current_mc is not None

            else "N/A"
        )


        multiplier_text = (

            f"{multiplier:.2f}x"

            if multiplier is not None

            else "N/A"
        )


        text += (

            f"🟢 {project_name}\n"
            f"👤 {kol_username}\n"
            f"💰 Call MC: {call_mc_text}\n"
            f"📈 Current MC: {current_mc_text}\n"
            f"🚀 Multiplier: {multiplier_text}\n"
            f"⏱️ {call_time or 'N/A'}\n\n"
        )


        if original_call_link:

            text += (
                f"🔎 Call: "
                f"{original_call_link}\n"
            )


        if kol_link:

            text += (
                f"💍 KOL: "
                f"{kol_link}\n"
            )


        if project_link:

            text += (
                f"🪙 Project: "
                f"{project_link}\n"
            )


        text += "\n"


    await query.edit_message_text(

        text,

        disable_web_page_preview=False,

        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data="back_menu"
                )
            ]
        ]),
    )


# =========================================================
# KOL LEADERBOARD
# =========================================================

def get_kol_leaderboard():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            v.channel_username,
            COUNT(c.id) AS total_calls,
            SUM(
                CASE
                    WHEN c.multiplier >= 2
                    THEN 1
                    ELSE 0
                END
            ) AS two_x_calls,
            MAX(c.multiplier) AS best_multiplier
        FROM verified_channels v
        LEFT JOIN calls c
            ON LOWER(
                REPLACE(c.kol_username, '@', '')
            ) = LOWER(v.channel_username)
            AND c.created_at >= v.verified_at
        GROUP BY v.channel_username
        HAVING COUNT(c.id) > 0
        ORDER BY
            total_calls DESC,
            two_x_calls DESC,
            best_multiplier DESC
        LIMIT 10
    """)

    results = cursor.fetchall()

    conn.close()

    return results


# =========================================================
# SHOW KOL LEADERBOARD
# =========================================================

async def show_kol_leaderboard(query):

    leaderboard = get_kol_leaderboard()

    if not leaderboard:

        await query.edit_message_text(

            "📊 KOL Leaderboard\n\n"
            "No leaderboard data available yet.\n\n"
            "Verified KOLs will appear here "
            "after their calls are tracked.",

            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data="back_menu"
                    )
                ]
            ]),
        )

        return


    text = (
        "📊 <b>KOL LEADERBOARD</b>\n\n"
    )


    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]


    for index, row in enumerate(
        leaderboard
    ):

        channel_username = row[0]
        total_calls = row[1] or 0
        two_x_calls = row[2] or 0
        best_multiplier = row[3] or 0


        if index < 3:

            rank = medals[index]

        else:

            rank = (
                f"<b>#{index + 1}</b>"
            )


        channel_link = (
            f"https://t.me/"
            f"{channel_username.lstrip('@')}"
        )


        safe_channel = html.escape(
            "@" + channel_username.lstrip("@")
        )


        text += (

            f'{rank} '
            f'<a href="{channel_link}">'
            f'{safe_channel}'
            f'</a>\n'

            f"📞 Calls: {total_calls}\n"

            f"🚀 2x+: {two_x_calls}\n"

            f"🔥 Best: "
            f"{best_multiplier:.2f}x\n\n"
        )


    text += (
        "📌 Rankings are based on tracked calls "
        "after KOL verification."
    )


    await query.edit_message_text(

        text,

        parse_mode="HTML",

        disable_web_page_preview=True,

        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data="back_menu"
                )
            ]
        ]),
    )


# =========================================================
# SEARCH KOL
# =========================================================

async def search_kol(query):

    await query.edit_message_text(

        "🔎 Search KOL\n\n"
        "Send the Telegram KOL channel username "
        "or link.\n\n"

        "Example:\n"
        "@CRYPTO_RAVEN_CALL\n\n"

        "or\n"
        "https://t.me/CRYPTO_RAVEN_CALL",

        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data="back_menu"
                )
            ]
        ]),
    )


# =========================================================
# SHOW KOL RESULTS
# =========================================================

async def show_kol_results(
    update,
    channel
):

    verified = get_verified_channel(
        channel
    )


    if not verified:

        await update.message.reply_text(

            "❌ KOL Not Verified\n\n"
            f"{channel} isn't verified on KOLPulse yet.\n\n"
            "Please verify the channel first "
            "using 📡 Track My Channel.",

            reply_markup=main_menu(),
        )

        return


    verified_at = verified[3]


    calls = get_calls_for_kol_after_verification(
        channel,
        verified_at
    )


    if not calls:

        await update.message.reply_text(

            "🔎 KOL Search\n\n"

            f"📡 KOL: {channel}\n"
            "🟢 Status: Verified\n\n"

            "No tracked calls were found after "
            "this channel was verified.\n\n"

            "KOLPulse will show new tracked calls here.",

            reply_markup=main_menu(),
        )

        return


    text = (

        "🔎 KOL RESULTS\n\n"

        f"📡 KOL: {channel}\n"
        "🟢 Status: Verified\n\n"
    )


    for call in calls[:10]:

        (
            call_id,
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
            created_at,
        ) = call


        call_mc_text = (

            f"${call_mc:,.0f}"

            if call_mc is not None

            else "N/A"
        )


        current_mc_text = (

            f"${current_mc:,.0f}"

            if current_mc is not None

            else "N/A"
        )


        multiplier_text = (

            f"{multiplier:.2f}x"

            if multiplier is not None

            else "N/A"
        )


        text += (

            f"🟣 {project_name}\n"

            f"💰 Call MC: "
            f"{call_mc_text}\n"

            f"📈 Current MC: "
            f"{current_mc_text}\n"

            f"🚀 Multiplier: "
            f"{multiplier_text}\n"

            f"⏱️ "
            f"{call_time or 'N/A'}\n"
        )


        if original_call_link:

            text += (
                f"🔎 Call: "
                f"{original_call_link}\n"
            )


        if project_link:

            text += (
                f"🪙 Project: "
                f"{project_link}\n"
            )


        text += "\n"


    await update.message.reply_text(

        text,

        disable_web_page_preview=False,

        reply_markup=main_menu(),
    )


# =========================================================
# AUTOMATIC CHANNEL CALL DETECTOR
# =========================================================
#
# ALL VERIFIED / APPROVED CHANNELS
#
# No Raven-only restriction.
#
# Requirements:
# - Bot must be Admin in tracked channel
# - Channel must be verified in database
# - Post must contain a detectable CA/Contract
#
# MC is OPTIONAL.
#
# =========================================================

async def channel_post_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    # -----------------------------------------------------
    # CHANNEL POST
    # -----------------------------------------------------

    message = update.channel_post

    if not message:

        return


    chat = message.chat


    # -----------------------------------------------------
    # PUBLIC CHANNEL REQUIRED
    # -----------------------------------------------------

    if not chat.username:

        print(
            "⚠️ Ignored channel post: "
            "channel has no public username."
        )

        return


    channel = normalize_channel(
        chat.username
    )


    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    print(
        f"📨 CHANNEL POST RECEIVED: "
        f"{channel}"
    )


    # -----------------------------------------------------
    # TEXT + CAPTION
    # -----------------------------------------------------

    text = (

        message.text

        or message.caption

        or ""
    )


    if not text:

        print(
            f"⏭️ Empty post ignored from "
            f"{channel}"
        )

        return


    # -----------------------------------------------------
    # VERIFIED CHANNEL ONLY
    # -----------------------------------------------------

    if not is_verified_channel(
        channel
    ):

        print(
            f"⏭️ Unverified channel ignored: "
            f"{channel}"
        )

        return


    print(
        f"✅ VERIFIED KOL DETECTED: "
        f"{channel}"
    )


    # -----------------------------------------------------
    # CONTRACT / CA
    # -----------------------------------------------------

    contract = parse_contract(
        text
    )


    if not contract:

        print(
            f"⏭️ No CA/Contract found "
            f"in {channel} post."
        )

        return


    print(
        f"🔗 CA/Contract detected: "
        f"{contract}"
    )


    # -----------------------------------------------------
    # MARKET CAP
    # MC IS OPTIONAL
    # -----------------------------------------------------

    call_mc = parse_market_cap(
        text
    )


    if call_mc is None:

        print(
            f"ℹ️ MC not found in "
            f"{channel} post."
        )

        print(
            "➡️ Call will still be tracked "
            "with MC = N/A."
        )

    else:

        print(
            f"💰 Market Cap detected: "
            f"${call_mc:,.0f}"
        )


    # -----------------------------------------------------
    # PROJECT NAME
    # -----------------------------------------------------

    project_name = parse_project_name(
        text,
        contract
    )


    print(
        f"🪙 Project detected: "
        f"{project_name}"
    )


    # -----------------------------------------------------
    # TOKEN SYMBOL
    # -----------------------------------------------------

    token_symbol = detect_token_symbol(
        text,
        project_name,
        contract
    )


    print(
        f"🔮 Token detected: "
        f"{token_symbol}"
    )


    # -----------------------------------------------------
    # CHAIN
    # -----------------------------------------------------

    chain_symbol = detect_chain_symbol(
        text,
        contract
    )


    print(
        f"⛓️ Chain detected: "
        f"{chain_symbol}"
    )


    # -----------------------------------------------------
    # PROJECT LINK
    # -----------------------------------------------------

    project_link = parse_project_link(
        text
    )


    if project_link:

        print(
            f"🔗 Project link detected: "
            f"{project_link}"
        )


    # -----------------------------------------------------
    # TELEGRAM LINKS
    # -----------------------------------------------------

    original_call_link = (
        f"https://t.me/"
        f"{chat.username}/"
        f"{message.message_id}"
    )


    kol_link = (
        f"https://t.me/"
        f"{chat.username}"
    )


    # -----------------------------------------------------
    # SAVE CALL
    # -----------------------------------------------------

    try:

        call_id = add_call(

            kol_username=channel,

            project_name=project_name,

            kol_link=kol_link,

            project_link=project_link,

            original_call_link=(
                original_call_link
            ),

            call_mc=call_mc,

            current_mc=call_mc,

            multiplier=1,

            call_time=(
                datetime.utcnow()
                .strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            ),

            video_file_id=None,

            status="live",
        )


        print(
            "✅ CALL DETECTED AND SAVED"
        )

        print(
            f"   KOL: {channel}"
        )

        print(
            f"   Project: {project_name}"
        )

        print(
            f"   Token: {token_symbol}"
        )

        print(
            f"   Contract: {contract}"
        )

        print(
            "   Call MC: "
            f"{format_market_cap(call_mc)}"
        )

        print(
            f"   Call ID: {call_id}"
        )


    except Exception as error:

        print(
            "❌ Could not save detected call: "
            f"{type(error).__name__}: {error}"
        )

        return


    # -----------------------------------------------------
    # SEND ALERT TO KOLPULSE LIVE
    # -----------------------------------------------------

    try:

        safe_channel = html.escape(
            channel
        )

        safe_token = html.escape(
            token_symbol
        )

        safe_contract = html.escape(
            contract
        )

        safe_chain = html.escape(
            chain_symbol
        )

        mc_display = format_market_cap(
            call_mc
        )


        alert_text = (

            f'🔮 <a href="{kol_link}">'
            f'{safe_channel}</a> '
            f'Dropped a Call 🔮\n\n'

            f"🔮 Token Symbol   🔮 "
            f"{safe_token}\n"

            f"🔮 Current MC     🔮 "
            f"{mc_display}\n"

            f"🔮 Chain Symbol   🔮 "
            f"{safe_chain}\n\n"

            "We've started tracking it and "
            "will continue to send performance "
            "alerts as the token progresses. "
            "Stay tuned!\n\n"

            f"Ca: <code>"
            f"{safe_contract}"
            f"</code>\n\n"

            f'🔮 <a href="{original_call_link}">'
            f'CALL</a>    '

            f'🔮 <a href="{kol_link}">'
            f'KOL</a>    '

            f'🔮 <a href="{BOT_LINK}">'
            f'BOT</a>'
        )


        await context.bot.send_message(

            chat_id=LIVE_CHANNEL,

            text=alert_text,

            parse_mode="HTML",

            disable_web_page_preview=True,
        )


        print(
            f"✅ Alert sent to "
            f"{LIVE_CHANNEL}"
        )


    except Exception as error:

        print(
            "❌ Could not send alert to "
            f"{LIVE_CHANNEL}: "
            f"{type(error).__name__}: {error}"
        )


    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )


# =========================================================
# BUTTON HANDLER
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    data = query.data


    # =====================================================
    # KOL LEADERBOARD
    # =====================================================

    if data == "leaderboard":

        await query.answer()

        try:

            await show_kol_leaderboard(
                query
            )

        except Exception as error:

            print(
                "Leaderboard error: "
                f"{type(error).__name__}: {error}"
            )

            await query.edit_message_text(

                "⚠️ KOL Leaderboard "
                "could not be loaded.\n\n"
                "Please try again.",

                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "⬅️ Back",
                            callback_data="back_menu"
                        )
                    ]
                ]),
            )

        return


    # =====================================================
    # TRACK MY CHANNEL
    # =====================================================

    if data == "track_channel":

        await query.answer()


        context.user_data[
            "waiting_for_channel"
        ] = False

        context.user_data[
            "waiting_for_kol_search"
        ] = False

        context.user_data[
            "channel_admin_check"
        ] = False


        await query.edit_message_text(

            "📡 Track My Channel\n\n"

            "Before submitting your channel, "
            "you must add our bot as an Admin:\n\n"

            f"🤖 {BOT_USERNAME}\n\n"

            "Please add the bot as an Admin "
            "in your Telegram channel.\n\n"

            "After you have added the bot, "
            "click the button below.",

            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🤖 I Added Bot as Admin",
                        callback_data=(
                            "check_bot_admin"
                        )
                    )
                ],

                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data=(
                            "back_menu"
                        )
                    )
                ]
            ]),
        )

        return


    # =====================================================
    # I ADDED BOT AS ADMIN
    # =====================================================

    if data == "check_bot_admin":

        await query.answer()


        context.user_data[
            "waiting_for_channel"
        ] = True

        context.user_data[
            "waiting_for_kol_search"
        ] = False

        context.user_data[
            "channel_admin_check"
        ] = True


        await query.edit_message_text(

            "📡 Track My Channel\n\n"

            "Send your Telegram channel username.\n\n"

            "Example:\n"
            "@MyCryptoChannel\n\n"

            "Make sure the channel username "
            "is correct.\n\n"

            f"🔐 KOLPulse will verify that "
            f"{BOT_USERNAME} is an Admin in "
            "that channel before your request "
            "can be submitted.",

            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data=(
                            "back_menu"
                        )
                    )
                ]
            ]),
        )

        return


    # =====================================================
    # SEARCH KOL
    # =====================================================

    if data == "search_kol":

        await query.answer()


        context.user_data[
            "waiting_for_channel"
        ] = False

        context.user_data[
            "waiting_for_kol_search"
        ] = True


        await search_kol(
            query
        )

        return


    # =====================================================
    # BACK TO MENU
    # =====================================================

    if data == "back_menu":

        await query.answer()


        context.user_data[
            "waiting_for_channel"
        ] = False

        context.user_data[
            "waiting_for_kol_search"
        ] = False

        context.user_data[
            "channel_admin_check"
        ] = False


        await query.edit_message_text(

            "⚡ KOLPulse Main Menu\n\n"
            "Choose an option below:",

            reply_markup=main_menu(),
        )

        return


    # =====================================================
    # ACCEPT REQUEST
    # =====================================================

    if data.startswith(
        "accept:"
    ):

        await query.answer()


        parts = data.split(
            ":",
            2
        )


        if len(parts) != 3:

            return


        try:

            user_id = int(
                parts[1]
            )

        except ValueError:

            return


        channel = normalize_channel(
            parts[2]
        )


        if str(
            query.message.chat.id
        ) != GROUP_CHAT_ID:

            await query.answer(
                "Not authorized.",
                show_alert=True
            )

            return


        # -------------------------------------------------
        # ADMIN CHECK
        # -------------------------------------------------

        try:

            member = (
                await context.bot.get_chat_member(
                    chat_id=query.message.chat.id,
                    user_id=query.from_user.id,
                )
            )


            if member.status not in [
                "administrator",
                "creator"
            ]:

                await query.answer(
                    "Only group admins can approve requests.",
                    show_alert=True
                )

                return


        except Exception as error:

            print(
                f"Admin check error: {error}"
            )

            await query.answer(
                "Could not verify admin.",
                show_alert=True
            )

            return


        # -------------------------------------------------
        # PREVENT DUPLICATE APPROVAL
        # -------------------------------------------------

        try:

            existing_verified = (
                get_verified_channel(
                    channel
                )
            )


            if existing_verified:

                update_request_status(
                    channel,
                    "approved"
                )


                await query.edit_message_text(

                    "📡 CHANNEL TRACKING REQUEST\n\n"

                    f"📺 Channel: {channel}\n\n"

                    "🟢 STATUS: ALREADY APPROVED"
                )

                return


        except Exception as error:

            print(
                "Existing verification "
                f"check error: {error}"
            )


        # -------------------------------------------------
        # SAVE VERIFIED CHANNEL
        # -------------------------------------------------

        try:

            verified_at = (
                add_verified_channel(
                    channel_username=channel,
                    user_id=user_id,
                )
            )


            update_request_status(
                channel,
                "approved"
            )


            print(
                "✅ Verified channel saved: "
                f"{channel} at {verified_at}"
            )


        except Exception as error:

            print(
                "❌ Could not save verified channel: "
                f"{type(error).__name__}: {error}"
            )

            await query.answer(
                "Could not save verification.",
                show_alert=True
            )

            return


        # -------------------------------------------------
        # NOTIFY USER
        # -------------------------------------------------

        try:

            await context.bot.send_message(

                chat_id=user_id,

                text=(

                    "✅ Channel Approved!\n\n"

                    f"📡 Channel: {channel}\n\n"

                    "Your channel has been verified "
                    "on KOLPulse.\n\n"

                    "🔎 New KOL calls will now be "
                    "automatically tracked."
                ),
            )


        except Exception as error:

            print(
                f"Could not notify user: {error}"
            )


        # -------------------------------------------------
        # ADMIN NAME
        # -------------------------------------------------

        if query.from_user.username:

            admin_name = (
                f"@{query.from_user.username}"
            )

        else:

            admin_name = (
                query.from_user.full_name
            )


        approved_text = (

            "📡 CHANNEL TRACKING REQUEST\n\n"

            f"📺 Channel: {channel}\n\n"

            "🟢 STATUS: APPROVED\n\n"

            f"👮 Approved by: {admin_name}"
        )


        try:

            await query.edit_message_text(
                approved_text
            )

        except Exception as error:

            print(
                f"Could not update group message: "
                f"{error}"
            )

        return


    # =====================================================
    # REJECT REQUEST
    # =====================================================

    if data.startswith(
        "reject:"
    ):

        await query.answer()


        parts = data.split(
            ":",
            2
        )


        if len(parts) != 3:

            return


        try:

            user_id = int(
                parts[1]
            )

        except ValueError:

            return


        channel = normalize_channel(
            parts[2]
        )


        if str(
            query.message.chat.id
        ) != GROUP_CHAT_ID:

            await query.answer(
                "Not authorized.",
                show_alert=True
            )

            return


        # -------------------------------------------------
        # ADMIN CHECK
        # -------------------------------------------------

        try:

            member = (
                await context.bot.get_chat_member(
                    chat_id=query.message.chat.id,
                    user_id=query.from_user.id,
                )
            )


            if member.status not in [
                "administrator",
                "creator"
            ]:

                await query.answer(
                    "Only group admins can reject requests.",
                    show_alert=True
                )

                return


        except Exception as error:

            print(
                f"Admin check error: {error}"
            )

            await query.answer(
                "Could not verify admin.",
                show_alert=True
            )

            return


        # -------------------------------------------------
        # UPDATE REJECTED STATUS
        # -------------------------------------------------

        try:

            update_request_status(
                channel,
                "rejected"
            )

        except Exception as error:

            print(
                "Could not update rejected status: "
                f"{error}"
            )


        # -------------------------------------------------
        # NOTIFY USER
        # -------------------------------------------------

        try:

            await context.bot.send_message(

                chat_id=user_id,

                text=(

                    "❌ Channel Request Rejected\n\n"

                    f"📡 Channel: {channel}\n\n"

                    "Your tracking request was rejected "
                    "by KOLPulse.\n\n"

                    "You can submit the channel again "
                    "if needed."
                ),
            )

        except Exception as error:

            print(
                f"Could not notify user: {error}"
            )


        rejected_text = (

            "📡 CHANNEL TRACKING REQUEST\n\n"

            f"📺 Channel: {channel}\n\n"

            "🔴 STATUS: REJECTED"
        )


        try:

            await query.edit_message_text(
                rejected_text
            )

        except Exception as error:

            print(
                "Could not update rejected message: "
                f"{error}"
            )

        return


    # =====================================================
    # TOP KOLS
    # =====================================================

    if data == "top_kols":

        await query.answer()

        await query.edit_message_text(

            "🏆 Top KOLs\n\n"

            "Top performing verified KOLs "
            "will appear here.\n\n"

            "KOLPulse is tracking calls "
            "automatically.",

            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data=(
                            "back_menu"
                        )
                    )
                ]
            ]),
        )

        return


    # =====================================================
    # SUPPORT
    # =====================================================

    if data == "support":

        await query.answer()

        await query.edit_message_text(

            "🆘 KOLPulse Support\n\n"

            "Need help with verification, "
            "tracking or your KOL channel?\n\n"

            "Contact:\n"
            "@ZENITP2P",

            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data=(
                            "back_menu"
                        )
                    )
                ]
            ]),
        )

        return


    # =====================================================
    # UNKNOWN
    # =====================================================

    await query.answer()

    await query.edit_message_text(

        "⚠️ Unknown option.",

        reply_markup=main_menu(),
    )


# =========================================================
# VERIFY BOT ADMIN IN CHANNEL
# =========================================================

async def verify_bot_is_channel_admin(
    context,
    channel
):

    channel = normalize_channel(
        channel
    )


    try:

        chat = await context.bot.get_chat(
            channel
        )


        bot_member = (
            await context.bot.get_chat_member(
                chat_id=chat.id,
                user_id=context.bot.id
            )
        )


        print(
            f"🔐 Bot status in {channel}: "
            f"{bot_member.status}"
        )


        if bot_member.status in [
            "administrator",
            "creator"
        ]:

            return (
                True,
                chat,
                bot_member.status
            )


        return (
            False,
            chat,
            bot_member.status
        )


    except Exception as error:

        print(
            "❌ Could not verify bot admin status "
            f"for {channel}: "
            f"{type(error).__name__}: {error}"
        )


        return (
            False,
            None,
            None
        )


# =========================================================
# TEXT MESSAGE HANDLER
# =========================================================

async def channel_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:

        return


    if not update.message.text:

        return


    message_text = (
        update.message.text.strip()
    )


    # =====================================================
    # SEARCH KOL
    # =====================================================

    if context.user_data.get(
        "waiting_for_kol_search"
    ):

        channel = normalize_channel(
            message_text
        )


        context.user_data[
            "waiting_for_kol_search"
        ] = False


        await show_kol_results(
            update,
            channel
        )

        return


    # =====================================================
    # TRACK MY CHANNEL
    # =====================================================

    if not context.user_data.get(
        "waiting_for_channel"
    ):

        return


    channel = normalize_channel(
        message_text
    )


    context.user_data[
        "waiting_for_channel"
    ] = False


    # =====================================================
    # VERIFY BOT ADMIN
    # =====================================================

    print(
        f"🔐 Checking bot Admin access "
        f"in {channel}..."
    )


    (
        bot_is_admin,
        telegram_chat,
        bot_status
    ) = await verify_bot_is_channel_admin(
        context,
        channel
    )


    if not bot_is_admin:

        context.user_data[
            "waiting_for_channel"
        ] = True


        await update.message.reply_text(

            "❌ Bot Is Not Admin Yet\n\n"

            f"📡 Channel: {channel}\n\n"

            "Please add:\n"
            f"🤖 {BOT_USERNAME}\n\n"

            "as an Admin in your Telegram channel.\n\n"

            "After adding the bot as Admin, "
            "send your channel username again.\n\n"

            "⚠️ Your request has NOT been submitted.",

            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🤖 I Added Bot as Admin",
                        callback_data=(
                            "check_bot_admin"
                        )
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data=(
                            "back_menu"
                        )
                    )
                ]
            ]),
        )

        return


    # =====================================================
    # BOT IS ADMIN
    # =====================================================

    print(
        f"✅ KOLPulse bot is Admin in "
        f"{channel}"
    )


    # =====================================================
    # CHECK REQUEST STATUS
    # =====================================================

    try:

        status = get_request_status(
            channel
        )


    except Exception as error:

        print(
            "❌ Channel status check failed: "
            f"{type(error).__name__}: {error}"
        )


        await update.message.reply_text(

            "⚠️ Could not check your "
            "channel status.\n\n"
            "Please try again in a moment.",

            reply_markup=main_menu(),
        )

        return


    # =====================================================
    # ALREADY APPROVED
    # =====================================================

    if status == "approved":

        await update.message.reply_text(

            "✅ Channel Already Approved!\n\n"

            f"📡 Channel: {channel}\n\n"

            "Your channel is already verified "
            "on KOLPulse.\n\n"

            "🔎 New calls can already be tracked.",

            reply_markup=main_menu(),
        )

        return


    # =====================================================
    # ALREADY PENDING
    # =====================================================

    if status == "pending":

        await update.message.reply_text(

            "⏳ Channel Already Pending!\n\n"

            f"📡 Channel: {channel}\n\n"

            "Your tracking request is already "
            "waiting for admin approval.\n\n"

            "Please wait for the admin decision.",

            reply_markup=main_menu(),
        )

        return


    # =====================================================
    # USER INFORMATION
    # =====================================================

    user = update.effective_user


    if user.username:

        user_display = (
            f"@{user.username}"
        )

    else:

        user_display = (
            user.full_name
        )


    user_id = user.id


    # =====================================================
    # SAVE AS PENDING
    # =====================================================

    try:

        created = save_pending_request(
            channel,
            user_id
        )


        if not created:

            await update.message.reply_text(

                "⏳ Channel Already Pending!\n\n"

                f"📡 Channel: {channel}\n\n"

                "Your tracking request is already "
                "waiting for admin approval.",

                reply_markup=main_menu(),
            )

            return


    except Exception as error:

        print(
            "❌ Could not save pending request: "
            f"{type(error).__name__}: {error}"
        )


        await update.message.reply_text(

            "⚠️ Could not create your "
            "tracking request.\n\n"
            "Please try again.",

            reply_markup=main_menu(),
        )

        return


    current_time = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


    # =====================================================
    # ADMIN GROUP NOTIFICATION
    # =====================================================

    notification = (

        "📡 NEW CHANNEL TRACKING REQUEST\n\n"

        f"👤 User: {user_display}\n"

        f"🆔 Telegram ID: {user_id}\n\n"

        f"📺 Channel: {channel}\n"

        f"🔗 Link: https://t.me/"
        f"{channel.lstrip('@')}\n\n"

        "🤖 Bot Admin: ✅ Verified\n"

        f"⏰ Time: {current_time}\n\n"

        "👇 Admin action required:"
    )


    group_sent = False


    if GROUP_CHAT_ID:

        try:

            group_chat_id = int(
                GROUP_CHAT_ID
            )


            await context.bot.send_message(

                chat_id=group_chat_id,

                text=notification,

                reply_markup=request_buttons(
                    user_id,
                    channel
                ),

                disable_web_page_preview=True,
            )


            group_sent = True


            print(
                "✅ Group notification "
                "sent successfully."
            )


        except Exception as error:

            print(
                "❌ GROUP NOTIFICATION ERROR: "
                f"{type(error).__name__}: {error}"
            )


    else:

        print(
            "❌ GROUP_CHAT_ID secret is empty."
        )


    # =====================================================
    # USER CONFIRMATION
    # =====================================================

    if group_sent:

        confirmation = (

            "📡 Channel Submitted Successfully!\n\n"

            f"📺 Channel: {channel}\n"

            "🤖 Bot Admin: ✅ Verified\n\n"

            "⏳ Status: Pending Admin Approval\n\n"

            "Your tracking request has been "
            "sent to KOLPulse.\n\n"

            "Please wait for the admin decision."
        )


    else:

        confirmation = (

            "⚠️ Channel received!\n\n"

            f"📡 Channel: {channel}\n"

            "🤖 Bot Admin: ✅ Verified\n\n"

            "Your request was saved, but the "
            "admin notification could not be sent.\n\n"

            "Please contact support."
        )


    await update.message.reply_text(

        confirmation,

        reply_markup=main_menu(),
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise ValueError(
            "BOT_TOKEN is not configured."
        )


    if not GROUP_CHAT_ID:

        raise ValueError(
            "GROUP_CHAT_ID is not configured."
        )


    # -----------------------------------------------------
    # DATABASE
    # -----------------------------------------------------

    init_database()

    ensure_tracking_requests_table()


    print(
        "🚀 KOLPulse Bot starting..."
    )


    print(
        f"📡 Admin Group: {GROUP_CHAT_ID}"
    )


    print(
        "📡 Monitoring: "
        "ALL VERIFIED / APPROVED CHANNELS"
    )


    print(
        "📡 Raven-only restriction: DISABLED"
    )


    print(
        f"🤖 Bot: {BOT_USERNAME}"
    )


    print(
        f"📡 Live Destination: "
        f"{LIVE_CHANNEL}"
    )


    print(
        "🔐 Channel Admin verification enabled."
    )


    print(
        "🧠 Flexible CA/Contract parser enabled."
    )


    print(
        "💰 MC is OPTIONAL for call detection."
    )


    print(
        "🔗 Project link detection enabled."
    )


    # -----------------------------------------------------
    # APPLICATION
    # -----------------------------------------------------

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )


    # =====================================================
    # COMMANDS
    # =====================================================

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    app.add_handler(
        CommandHandler(
            "groupid",
            groupid
        )
    )


    # =====================================================
    # CALLBACK BUTTONS
    # =====================================================

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )


    # =====================================================
    # CHANNEL POSTS
    # =====================================================

    app.add_handler(
        MessageHandler(
            filters.UpdateType.CHANNEL_POST,
            channel_post_handler,
        )
    )


    # =====================================================
    # TEXT MESSAGES
    # =====================================================

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            channel_message,
        )
    )


    print(
        "✅ KOLPulse Bot is now running..."
    )


    print(
        "⏳ Polling Telegram..."
    )


    app.run_polling(
        drop_pending_updates=False
    )


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":

    main() 
