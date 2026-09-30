import os
import re
import html
import json
import asyncio
import urllib.parse
import urllib.request

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

DEX_API_BASE = "https://api.dexscreener.com"

TRACK_INTERVAL_SECONDS = 60

# Minimum X milestone that should trigger a pump alert.
# Can be changed at runtime with: /setmilestone 2
MIN_PUMP_MILESTONE = 2


# =========================================================
# DEXSCREENER CHAIN MAP
# =========================================================

DEX_CHAIN_MAP = {
    "SOL": "solana",
    "ETH": "ethereum",
    "BASE": "base",
    "BSC": "bsc",
    "ARB": "arbitrum",
    "POLY": "polygon",
    "AVAX": "avalanche",
    "OP": "optimism",
    "ZKSYNC": "zksync",
    "LINEA": "linea",
    "BLAST": "blast",
    "SONIC": "sonic",
    "MONAD": "monad",
    "HYPER": "hyperevm",
}


# =========================================================
# CHANNEL NORMALIZER
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


# =========================================================
# TRACKING REQUEST TABLE
# =========================================================

def ensure_tracking_requests_table():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(""" CREATE TABLE IF NOT EXISTS channel_tracking_requests ( id INTEGER PRIMARY KEY AUTOINCREMENT, channel_username TEXT NOT NULL UNIQUE, user_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, updated_at TEXT NOT NULL ) """)

    conn.commit()
    conn.close()


# =========================================================
# CALL TRACKING COLUMNS
# =========================================================

def ensure_call_tracking_columns():

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            "PRAGMA table_info(calls)"
        )

        columns = {
            row[1]
            for row in cursor.fetchall()
        }

        if "contract" not in columns:

            cursor.execute(""" ALTER TABLE calls ADD COLUMN contract TEXT """)

            print(
                "✅ Added calls.contract"
            )

        if "chain" not in columns:

            cursor.execute(""" ALTER TABLE calls ADD COLUMN chain TEXT """)

            print(
                "✅ Added calls.chain"
            )

        if "ath_mc" not in columns:

            cursor.execute(""" ALTER TABLE calls ADD COLUMN ath_mc REAL DEFAULT 0 """)

            print(
                "✅ Added calls.ath_mc"
            )

        if "last_milestone" not in columns:

            cursor.execute(""" ALTER TABLE calls ADD COLUMN last_milestone INTEGER DEFAULT 1 """)

            print(
                "✅ Added calls.last_milestone"
            )

        conn.commit()

    except Exception as error:

        print(
            "❌ Could not prepare tracking columns: "
            f"{type(error).__name__}: {error}"
        )

    finally:

        conn.close()


# =========================================================
# REQUEST STATUS
# =========================================================

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

    cursor.execute(""" SELECT status FROM channel_tracking_requests WHERE LOWER(REPLACE(channel_username, '@', '')) = ? ORDER BY id DESC LIMIT 1 """, (
        clean,
    ))

    row = cursor.fetchone()

    conn.close()

    if not row:

        return None

    return row[0]


# =========================================================
# SAVE PENDING REQUEST
# =========================================================

def save_pending_request( channel, user_id ):

    channel = normalize_channel(channel)

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(""" SELECT id, status FROM channel_tracking_requests WHERE LOWER(REPLACE(channel_username, '@', '')) = ? ORDER BY id DESC LIMIT 1 """, (
        channel.lstrip("@").lower(),
    ))

    row = cursor.fetchone()

    if row:

        request_id, status = row

        if status == "pending":

            conn.close()

            return False

        cursor.execute(""" UPDATE channel_tracking_requests SET user_id = ?, status = 'pending', updated_at = ? WHERE id = ? """, (
            user_id,
            now,
            request_id,
        ))

    else:

        cursor.execute(""" INSERT INTO channel_tracking_requests ( channel_username, user_id, status, created_at, updated_at ) VALUES (?, ?, 'pending', ?, ?) """, (
            channel,
            user_id,
            now,
            now,
        ))

    conn.commit()
    conn.close()

    return True


# =========================================================
# UPDATE REQUEST STATUS
# =========================================================

def update_request_status( channel, status ):

    channel = normalize_channel(channel)

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(""" UPDATE channel_tracking_requests SET status = ?, updated_at = ? WHERE LOWER(REPLACE(channel_username, '@', '')) = ? """, (
        status,
        now,
        channel.lstrip("@").lower(),
    ))

    conn.commit()
    conn.close()


# =========================================================
# MAIN MENU
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
# ADMIN REQUEST BUTTONS
# =========================================================

def request_buttons( user_id, channel ):

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

async def start( update: Update, context: ContextTypes.DEFAULT_TYPE ):

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

async def groupid( update: Update, context: ContextTypes.DEFAULT_TYPE ):

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

    try:

        value = float(value)

    except Exception:

        return "N/A"

    if value <= 0:

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
# NUMBER CONVERTER
# =========================================================

def convert_number( number, suffix=None ):

    try:

        value = float(number)

    except Exception:

        return None

    suffix = (
        suffix or ""
    ).upper()

    if suffix == "K":

        value *= 1_000

    elif suffix == "M":

        value *= 1_000_000

    elif suffix == "B":

        value *= 1_000_000_000

    return value


# =========================================================
# TOKEN SYMBOL
# =========================================================

def detect_token_symbol( text, project_name=None ):

    source = text or ""

    match = re.search(
        r"(?<![A-Za-z0-9_])\$([A-Za-z][A-Za-z0-9_]{0,30})",
        source
    )

    if match:

        return "$" + match.group(1)

    patterns = [

        r"(?:token\s*symbol|symbol|ticker)"
        r"\s*[:=\-]\s*\$?"
        r"([A-Za-z][A-Za-z0-9_]{0,30})",

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            source,
            re.IGNORECASE
        )

        if match:

            return "$" + match.group(1)

    if project_name:

        match = re.search(
            r"(?<![A-Za-z0-9_])\$([A-Za-z][A-Za-z0-9_]{0,30})",
            project_name
        )

        if match:

            return "$" + match.group(1)

    return "$TOKEN"


# =========================================================
# CONTRACT / CA
# =========================================================

def parse_contract(text):

    if not text:

        return None

    explicit_patterns = [

        r"(?:contract\s+address)"
        r"\s*[:=\-]?\s*"
        r"`?([A-Za-z0-9]{20,160})`?",

        r"(?:contract)"
        r"\s*[:=\-]?\s*"
        r"`?([A-Za-z0-9]{20,160})`?",

        r"(?:ca)"
        r"\s*[:=\-]?\s*"
        r"`?([A-Za-z0-9]{20,160})`?",
    ]

    for pattern in explicit_patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            value = match.group(1).strip()

            value = value.strip(
                "`'\"<>[](){}.,; "
            )

            if len(value) >= 20:

                return value

    dex_patterns = [

        r"https?://(?:www\.)?"
        r"dexscreener\.com/"
        r"[^/\s]+/"
        r"(0x[a-fA-F0-9]{20,160})",

        r"https?://(?:www\.)?"
        r"dexscreener\.com/"
        r"[^/\s]+/"
        r"([A-Za-z0-9]{20,160})",
    ]

    for pattern in dex_patterns:

        matches = re.findall(
            pattern,
            text,
            re.IGNORECASE
        )

        for value in matches:

            value = value.strip(
                "`'\"<>[](){}.,; "
            )

            if len(value) >= 20:

                return value

    evm_matches = re.findall(
        r"\b0x[a-fA-F0-9]{20,160}\b",
        text
    )

    if evm_matches:

        return evm_matches[0]

    candidates = re.findall(
        r"\b[A-HJ-NP-Za-km-z1-9]{32,100}\b",
        text
    )

    for candidate in candidates:

        if candidate.startswith(
            (
                "https",
                "www",
                "dexscreener",
                "telegram",
                "twitter",
            )
        ):

            continue

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
# DEX CHAIN DETECTION
# =========================================================

def detect_dex_chain(text):

    if not text:

        return None

    match = re.search(

        r"https?://(?:www\.)?"
        r"dexscreener\.com/"
        r"([^/\s]+)",

        text,

        re.IGNORECASE
    )

    if not match:

        return None

    chain = match.group(1).strip().lower()

    chain_map = {

        "ethereum": "ETH",
        "solana": "SOL",
        "base": "BASE",
        "bsc": "BSC",
        "arbitrum": "ARB",
        "polygon": "POLY",
        "avalanche": "AVAX",
        "optimism": "OP",
        "zksync": "ZKSYNC",
        "linea": "LINEA",
        "scroll": "SCROLL",
        "blast": "BLAST",
        "sonic": "SONIC",
        "monad": "MONAD",
        "hyperevm": "HYPER",
    }

    if chain in chain_map:

        return chain_map[chain]

    return chain.upper()


# =========================================================
# MARKET CAP DETECTION
# =========================================================

def parse_market_cap(text):

    if not text:

        return None

    patterns = [

        r"(?:market\s*cap|marketcap)"
        r"\s*(?:is|:|=|-)?\s*"
        r"\$?\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*([KMB])?\b",

        r"(?:current\s*mc)"
        r"\s*(?:is|:|=|-)?\s*"
        r"\$?\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*([KMB])?\b",

        r"\bmc\b"
        r"\s*(?:is|:|=|-)?\s*"
        r"\$?\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*([KMB])?\b",

        r"\$?\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*([KMB])?"
        r"\s*(?:mc|market\s*cap)\b",

        r"(?:current\s+chart|chart|"
        r"current\s+market\s+cap)"
        r".{0,100}?"
        r"\$?\s*"
        r"([0-9]+(?:\.[0-9]+)?)"
        r"\s*([KMB])?"
        r"\s*mc\b",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            return convert_number(
                match.group(1),
                match.group(2)
            )

    return None


# =========================================================
# PROJECT LINKS
# =========================================================

def parse_project_links(text):

    if not text:

        return {
            "project_link": None,
            "dex_link": None,
            "x_link": None,
        }

    urls = re.findall(
        r"https?://[^\s<>()]+",
        text,
        re.IGNORECASE
    )

    cleaned_urls = []

    for url in urls:

        url = url.rstrip(
            ".,;:!?)]}>\"'"
        )

        cleaned_urls.append(
            url
        )

    dex_link = None
    x_link = None
    project_link = None

    for url in cleaned_urls:

        if "dexscreener.com/" in url.lower():

            dex_link = url

            break

    for url in cleaned_urls:

        lower = url.lower()

        if (
            "x.com/" in lower
            or "twitter.com/" in lower
        ):

            x_link = url

            break

    if x_link:

        project_link = x_link

    elif dex_link:

        project_link = dex_link

    elif cleaned_urls:

        project_link = cleaned_urls[0]

    return {
        "project_link": project_link,
        "dex_link": dex_link,
        "x_link": x_link,
    }


# =========================================================
# PROJECT NAME
# =========================================================

def parse_project_name( text, contract ):

    if not text:

        if contract:

            return contract[:12]

        return "Unknown Project"

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

    for line in text.splitlines():

        clean = line.strip()

        match = re.search(
            r"(?<![A-Za-z0-9_])"
            r"\$([A-Za-z][A-Za-z0-9_]{0,30})",
            clean
        )

        if match:

            return "$" + match.group(1)

    for line in text.splitlines():

        clean = line.strip()

        if not clean:

            continue

        if re.search(
            r"\$[A-Za-z][A-Za-z0-9_]*",
            clean
        ):

            if len(clean) <= 120:

                return clean

    x_match = re.search(
        r"(?:x\.com|twitter\.com)/"
        r"([A-Za-z0-9_]+)",
        text,
        re.IGNORECASE
    )

    if x_match:

        return x_match.group(1)

    if contract:

        return contract[:12]

    return "Unknown Project"


# =========================================================
# CHAIN DETECTION
# =========================================================

def detect_chain_symbol( text, contract=None ):

    dex_chain = detect_dex_chain(
        text
    )

    if dex_chain:

        return dex_chain

    source = (
        text or ""
    ).lower()

    if (
        "solana" in source
        or "sol:" in source
    ):

        return "SOL"

    if (
        "ethereum" in source
        or "eth:" in source
        or " eth " in source
    ):

        return "ETH"

    if (
        "base chain" in source
        or "base:" in source
    ):

        return "BASE"

    if (
        "bsc" in source
        or "bnb" in source
        or "binance smart chain" in source
    ):

        return "BSC"

    if (
        "arbitrum" in source
        or "arb:" in source
    ):

        return "ARB"

    if (
        "polygon" in source
        or "matic" in source
    ):

        return "POLY"

    if (
        "avalanche" in source
        or "avax" in source
    ):

        return "AVAX"

    if contract and re.fullmatch(
        r"0x[a-fA-F0-9]{20,160}",
        contract
    ):

        return "EVM"

    return "UNKNOWN"


# =========================================================
# VERIFIED CHANNEL
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
            "❌ Verification database error "
            f"for {channel}: "
            f"{type(error).__name__}: {error}"
        )

    return False


# =========================================================
# LIVE DEXSCREENER MARKET CAP
# =========================================================

def fetch_dex_market_cap_sync( contract, chain_symbol=None ):

    if not contract:

        return None

    contract = contract.strip()

    chain_id = DEX_CHAIN_MAP.get(
        (chain_symbol or "").upper()
    )

    urls = []

    if chain_id:

        encoded_contract = (
            urllib.parse.quote(
                contract,
                safe=""
            )
        )

        urls.append(
            f"{DEX_API_BASE}/token-pairs/v1/"
            f"{chain_id}/{encoded_contract}"
        )

        urls.append(
            f"{DEX_API_BASE}/tokens/v1/"
            f"{chain_id}/{encoded_contract}"
        )

    encoded_query = urllib.parse.quote(
        contract,
        safe=""
    )

    urls.append(
        f"{DEX_API_BASE}/latest/dex/search"
        f"?q={encoded_query}"
    )

    for api_url in urls:

        try:

            request = urllib.request.Request(

                api_url,

                headers={
                    "User-Agent":
                    "KOLPulse/1.0"
                }
            )

            with urllib.request.urlopen(
                request,
                timeout=12
            ) as response:

                raw = response.read()

            data = json.loads(
                raw.decode("utf-8")
            )

            if isinstance(data, list):

                pairs = data

            elif isinstance(data, dict):

                pairs = (
                    data.get("pairs")
                    or []
                )

            else:

                pairs = []

            if not pairs:

                continue

            valid_pairs = []

            for pair in pairs:

                if not isinstance(
                    pair,
                    dict
                ):

                    continue

                market_cap = pair.get(
                    "marketCap"
                )

                if market_cap is None:

                    market_cap = pair.get(
                        "fdv"
                    )

                if market_cap is None:

                    continue

                try:

                    market_cap = float(
                        market_cap
                    )

                except Exception:

                    continue

                if market_cap <= 0:

                    continue

                liquidity = (
                    pair.get(
                        "liquidity"
                    )
                    or {}
                )

                try:

                    liquidity_usd = float(
                        liquidity.get(
                            "usd"
                        )
                        or 0
                    )

                except Exception:

                    liquidity_usd = 0

                valid_pairs.append(
                    (
                        market_cap,
                        liquidity_usd,
                        pair
                    )
                )

            if not valid_pairs:

                continue

            valid_pairs.sort(
                key=lambda item: item[1],
                reverse=True
            )

            return valid_pairs[0][0]

        except Exception as error:

            print(
                "⚠️ DexScreener request failed: "
                f"{type(error).__name__}: {error}"
            )

    return None


async def fetch_live_market_cap( contract, chain_symbol=None ):

    return await asyncio.to_thread(
        fetch_dex_market_cap_sync,
        contract,
        chain_symbol
    )


# =========================================================
# SAVE TRACKING METADATA
# =========================================================

def save_tracking_metadata( call_id, contract, chain, call_mc ):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(""" UPDATE calls SET contract = ?, chain = ?, ath_mc = ?, last_milestone = 1 WHERE id = ? """, (
        contract,
        chain,
        call_mc or 0,
        call_id,
    ))

    conn.commit()
    conn.close()


# =========================================================
# GET TRACKING CALLS
# =========================================================

def get_tracking_calls():

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(""" SELECT id, kol_username, project_name, kol_link, project_link, original_call_link, call_mc, current_mc, multiplier, call_time, status, created_at, contract, chain, ath_mc, last_milestone FROM calls WHERE contract IS NOT NULL AND contract != '' AND call_mc > 0 """)

        rows = cursor.fetchall()

    except Exception as error:

        print(
            "❌ Could not load tracking calls: "
            f"{type(error).__name__}: {error}"
        )

        rows = []

    finally:

        conn.close()

    return rows


# =========================================================
# MILESTONE CALCULATION
# =========================================================

def get_pump_milestone( multiplier ):

    if multiplier is None:

        return 1

    try:

        multiplier = float(
            multiplier
        )

    except Exception:

        return 1

    if multiplier < MIN_PUMP_MILESTONE:

        return 1

    return int(
        multiplier
    )


# =========================================================
# SET MINIMUM PUMP MILESTONE
# =========================================================

async def setmilestone( update: Update, context: ContextTypes.DEFAULT_TYPE ):

    global MIN_PUMP_MILESTONE

    # This command is intended for private bot chat.
    if update.effective_chat and update.effective_chat.type != "private":

        await update.message.reply_text(
            "⚠️ Use /setmilestone in the bot's private chat."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "⚙️ Current minimum milestone: "
            f"{MIN_PUMP_MILESTONE}X\n\n"
            "Usage:\n"
            "/setmilestone 2\n"
            "/setmilestone 3\n"
            "/setmilestone 5"
        )

        return

    raw_value = context.args[0].strip().upper()

    # Accept values such as 2, 2X, 3, 5X.
    if raw_value.endswith("X"):

        raw_value = raw_value[:-1]

    try:

        milestone = int(raw_value)

    except ValueError:

        await update.message.reply_text(
            "❌ Invalid milestone.\n\n"
            "Use a whole number, for example:\n"
            "/setmilestone 2"
        )

        return

    if milestone < 2:

        await update.message.reply_text(
            "❌ Minimum milestone is 2X.\n\n"
            "Example: /setmilestone 2"
        )

        return

    if milestone > 1000:

        await update.message.reply_text(
            "❌ Maximum milestone is 1000X."
        )

        return

    MIN_PUMP_MILESTONE = milestone

    await update.message.reply_text(
        "✅ Milestone setting updated!\n\n"
        f"🚀 Minimum pump alert: {MIN_PUMP_MILESTONE}X\n\n"
        "The live tracker will now send alerts starting "
        f"from {MIN_PUMP_MILESTONE}X."
    )


# =========================================================
# PUMP ALERT
# =========================================================

async def send_pump_alert( context, call_id, kol_username, project_name, call_mc, current_mc, multiplier, milestone, original_call_link, kol_link, contract ):

    safe_kol = html.escape(
        kol_username or "@KOL"
    )

    safe_project = html.escape(
        project_name or "$TOKEN"
    )

    safe_contract = html.escape(
        contract or "N/A"
    )

    call_mc_text = format_market_cap(
        call_mc
    )

    current_mc_text = format_market_cap(
        current_mc
    )

    alert_text = (

        f"🚀 <b>{milestone}X PUMP HIT!</b>\n\n"

        f"🔮 <b>{safe_project}</b>\n"

        f"👤 KOL: "
        f"<a href=\"{kol_link}\">"
        f"{safe_kol}"
        f"</a>\n\n"

        f"💰 Call MC: "
        f"{call_mc_text}\n"

        f"📈 Current MC: "
        f"{current_mc_text}\n"

        f"🚀 Performance: "
        f"<b>{multiplier:.2f}X</b>\n\n"

        f"CA: <code>"
        f"{safe_contract}"
        f"</code>\n\n"

        f"🔎 <a href=\"{original_call_link}\">"
        f"CALL"
        f"</a> "

        f"👤 <a href=\"{kol_link}\">"
        f"KOL"
        f"</a> "

        f"🤖 <a href=\"{BOT_LINK}\">"
        f"BOT"
        f"</a>"
    )

    try:

        await context.bot.send_message(

            chat_id=LIVE_CHANNEL,

            text=alert_text,

            parse_mode="HTML",

            disable_web_page_preview=True,
        )

        print(
            f"🚀 {milestone}X ALERT SENT "
            f"for call #{call_id}"
        )

        return True

    except Exception as error:

        print(
            f"❌ Could not send {milestone}X alert "
            f"for call #{call_id}: "
            f"{type(error).__name__}: {error}"
        )

        return False


# =========================================================
# UPDATE ONE CALL
# =========================================================

async def update_one_tracked_call( context, row ):

    (
        call_id,
        kol_username,
        project_name,
        kol_link,
        project_link,
        original_call_link,
        call_mc,
        old_current_mc,
        old_multiplier,
        call_time,
        status,
        created_at,
        contract,
        chain,
        old_ath_mc,
        old_last_milestone,
    ) = row

    if not contract:

        return

    if not call_mc:

        return

    try:

        call_mc = float(
            call_mc
        )

    except Exception:

        return

    if call_mc <= 0:

        return

    current_mc = await fetch_live_market_cap(
        contract,
        chain
    )

    if current_mc is None:

        print(
            f"⚠️ No live MC found "
            f"for call #{call_id}"
        )

        return

    try:

        current_mc = float(
            current_mc
        )

    except Exception:

        return

    if current_mc <= 0:

        return

    multiplier = (
        current_mc / call_mc
    )

    try:

        old_ath_mc = float(
            old_ath_mc or 0
        )

    except Exception:

        old_ath_mc = 0

    new_ath_mc = max(
        old_ath_mc,
        current_mc
    )

    milestone = get_pump_milestone(
        multiplier
    )

    try:

        old_last_milestone = int(
            old_last_milestone or 1
        )

    except Exception:

        old_last_milestone = 1

    new_last_milestone = max(
        old_last_milestone,
        milestone
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(""" UPDATE calls SET current_mc = ?, multiplier = ?, ath_mc = ?, last_milestone = ? WHERE id = ? """, (
        current_mc,
        multiplier,
        new_ath_mc,
        new_last_milestone,
        call_id,
    ))

    conn.commit()
    conn.close()

    print(
        f"📈 CALL #{call_id} | "
        f"{format_market_cap(call_mc)} → "
        f"{format_market_cap(current_mc)} | "
        f"{multiplier:.2f}X | "
        f"ATH {format_market_cap(new_ath_mc)}"
    )

    if (
        milestone >= MIN_PUMP_MILESTONE
        and milestone > old_last_milestone
    ):

        await send_pump_alert(

            context=context,

            call_id=call_id,

            kol_username=kol_username,

            project_name=project_name,

            call_mc=call_mc,

            current_mc=current_mc,

            multiplier=multiplier,

            milestone=milestone,

            original_call_link=(
                original_call_link
            ),

            kol_link=kol_link,

            contract=contract,
        )


# =========================================================
# BACKGROUND LIVE MC TRACKER
# =========================================================

async def live_mc_tracker( application ):

    print(
        "🚀 LIVE MC TRACKER STARTED"
    )

    while True:

        try:

            rows = get_tracking_calls()

            if rows:

                print(
                    f"🔄 Tracking "
                    f"{len(rows)} call(s)..."
                )

            for row in rows:

                try:

                    await update_one_tracked_call(
                        application,
                        row
                    )

                except Exception as error:

                    print(
                        "❌ Individual tracker error: "
                        f"{type(error).__name__}: "
                        f"{error}"
                    )

                await asyncio.sleep(
                    0.25
                )

        except Exception as error:

            print(
                "❌ Live tracker loop error: "
                f"{type(error).__name__}: "
                f"{error}"
            )

        await asyncio.sleep(
            TRACK_INTERVAL_SECONDS
        )


# =========================================================
# APPLICATION POST INIT
# =========================================================

async def post_init( application ):

    application.create_task(
        live_mc_tracker(
            application
        )
    )

    print(
        "✅ Background MC tracker launched."
    )


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

    text = (
        "🔥 LIVE CALLS\n\n"
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

        if multiplier is not None:

            multiplier_text = (
                f"{multiplier:.2f}x"
            )

        else:

            multiplier_text = "N/A"

        text += (

            f"🟢 {project_name}\n"

            f"👤 {kol_username}\n"

            f"💰 Call MC: "
            f"{format_market_cap(call_mc)}\n"

            f"📈 Current MC: "
            f"{format_market_cap(current_mc)}\n"

            f"🚀 Multiplier: "
            f"{multiplier_text}\n"

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

    cursor.execute(""" SELECT v.channel_username, COUNT(c.id) AS total_calls, SUM( CASE WHEN c.multiplier >= 2 THEN 1 ELSE 0 END ) AS two_x_calls, MAX(c.multiplier) AS best_multiplier FROM verified_channels v LEFT JOIN calls c ON LOWER( REPLACE(c.kol_username, '@', '') ) = LOWER( v.channel_username ) AND c.created_at >= v.verified_at GROUP BY v.channel_username HAVING COUNT(c.id) > 0 ORDER BY total_calls DESC, two_x_calls DESC, best_multiplier DESC LIMIT 10 """)

    results = cursor.fetchall()

    conn.close()

    return results


# =========================================================
# SHOW LEADERBOARD
# =========================================================

async def show_kol_leaderboard(query):

    leaderboard = (
        get_kol_leaderboard()
    )

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

        total_calls = (
            row[1] or 0
        )

        two_x_calls = (
            row[2] or 0
        )

        best_multiplier = (
            row[3] or 0
        )

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

            f"📞 Calls: "
            f"{total_calls}\n"

            f"🚀 2x+: "
            f"{two_x_calls}\n"

            f"🔥 Best: "
            f"{best_multiplier:.2f}x\n\n"
        )

    text += (
        "📌 Rankings are based on tracked "
        "calls after KOL verification."
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

        "Send the Telegram KOL channel "
        "username or link.\n\n"

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

async def show_kol_results( update, channel ):

    verified = get_verified_channel(
        channel
    )

    if not verified:

        await update.message.reply_text(

            "❌ KOL Not Verified\n\n"

            f"{channel} isn't verified "
            "on KOLPulse yet.\n\n"

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
            "this channel was verified.",

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

        if multiplier is not None:

            multiplier_text = (
                f"{multiplier:.2f}x"
            )

        else:

            multiplier_text = "N/A"

        text += (

            f"🟣 {project_name}\n"

            f"💰 Call MC: "
            f"{format_market_cap(call_mc)}\n"

            f"📈 Current MC: "
            f"{format_market_cap(current_mc)}\n"

            f"🚀 Multiplier: "
            f"{multiplier_text}\n"

            f"⏱️ {call_time or 'N/A'}\n"
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
# CHANNEL POST DETECTOR
# =========================================================

async def channel_post_handler( update: Update, context: ContextTypes.DEFAULT_TYPE ):

    message = update.channel_post

    if not message:

        return

    chat = message.chat

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

    # =====================================================
    # VIDEO DETECTION
    # =====================================================

    video_file_id = None
    video_type = None

    if message.video:

        video_file_id = (
            message.video.file_id
        )

        video_type = "video"

        print(
            "🎥 VIDEO ATTACHMENT DETECTED"
        )

    elif message.animation:

        video_file_id = (
            message.animation.file_id
        )

        video_type = "animation"

        print(
            "🎞️ ANIMATION ATTACHMENT DETECTED"
        )

    if video_file_id:

        print(
            f"🎥 Telegram file_id: "
            f"{video_file_id}"
        )

    # =====================================================
    # TEXT / CAPTION
    # =====================================================

    text = (
        message.text
        or message.caption
        or ""
    )

    if not text:

        print(
            f"⏭️ Empty post ignored "
            f"from {channel}"
        )

        return

    print(
        "📝 Post text received:"
    )

    print(
        text[:1500]
    )

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
    # CONTRACT
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
    # MC WRITTEN IN POST
    # -----------------------------------------------------

    parsed_mc = parse_market_cap(
        text
    )

    # -----------------------------------------------------
    # PROMOTION-TIME LIVE MC
    # -----------------------------------------------------

    print(
        "📡 Fetching promotion-time live MC..."
    )

    live_call_mc = await fetch_live_market_cap(
        contract,
        chain_symbol
    )

    if live_call_mc is not None:

        call_mc = live_call_mc

        print(
            "💰 LIVE PROMOTION MC: "
            f"{format_market_cap(call_mc)}"
        )

    else:

        call_mc = parsed_mc

        if call_mc is not None:

            print(
                "⚠️ DexScreener live MC unavailable."
            )

            print(
                "💰 Using MC written in post: "
                f"{format_market_cap(call_mc)}"
            )

        else:

            print(
                "⚠️ No live MC and no post MC."
            )

            print(
                "⏭️ Call will not be tracked "
                "until a valid Call MC exists."
            )

            return

    # -----------------------------------------------------
    # PROJECT
    # -----------------------------------------------------

    project_name = parse_project_name(
        text,
        contract
    )

    print(
        f"🪙 Project: "
        f"{project_name}"
    )

    # -----------------------------------------------------
    # TOKEN
    # -----------------------------------------------------

    token_symbol = detect_token_symbol(
        text,
        project_name
    )

    print(
        f"🔮 Token: "
        f"{token_symbol}"
    )

    # -----------------------------------------------------
    # LINKS
    # -----------------------------------------------------

    links = parse_project_links(
        text
    )

    project_link = links[
        "project_link"
    ]

    dex_link = links[
        "dex_link"
    ]

    if dex_link:

        print(
            f"📈 DexScreener: "
            f"{dex_link}"
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
    # DATABASE MC
    # -----------------------------------------------------

    database_mc = (
        call_mc
        if call_mc is not None
        else 0
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

            call_mc=database_mc,

            current_mc=database_mc,

            multiplier=1.0,

            call_time=(
                datetime.utcnow()
                .strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            ),

            # =================================================
            # IMPORTANT:
            # Save Telegram's original video file_id.
            # =================================================

            video_file_id=video_file_id,

            status="live",
        )

        print(
            "✅ CALL DETECTED AND SAVED"
        )

        print(
            f" Call ID: {call_id}"
        )

        if video_file_id:

            print(
                "🎥 Video file_id saved with call."
            )

    except Exception as error:

        print(
            "❌ Could not save detected call: "
            f"{type(error).__name__}: {error}"
        )

        return

    # -----------------------------------------------------
    # SAVE CONTRACT / CHAIN / ATH
    # -----------------------------------------------------

    try:

        save_tracking_metadata(
            call_id=call_id,
            contract=contract,
            chain=chain_symbol,
            call_mc=database_mc,
        )

        print(
            "💾 Tracking metadata saved."
        )

    except Exception as error:

        print(
            "❌ Could not save tracking metadata: "
            f"{type(error).__name__}: {error}"
        )

    # -----------------------------------------------------
    # SEND INITIAL CALL ALERT
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

            f"🔮 Token Symbol 🔮 "
            f"{safe_token}\n"

            f"🔮 Call MC 🔮 "
            f"{mc_display}\n"

            f"🔮 Chain Symbol 🔮 "
            f"{safe_chain}\n\n"

            "We've started tracking it and "
            "will send performance alerts "
            "when new X milestones are reached.\n\n"

            f"CA: <code>"
            f"{safe_contract}"
            f"</code>\n\n"

            f'🔮 <a href="{original_call_link}">'
            f'CALL</a> '

            f'🔮 <a href="{kol_link}">'
            f'KOL</a> '

            f'🔮 <a href="{BOT_LINK}">'
            f'BOT</a>'
        )

        # =================================================
        # IMPORTANT VIDEO SEND
        #
        # If the original KOL post has a video,
        # send it to KOLPulse Live with the alert
        # as its caption.
        #
        # If there is no video, send normal text.
        # =================================================

        if video_file_id:

            if video_type == "animation":

                await context.bot.send_animation(

                    chat_id=LIVE_CHANNEL,

                    animation=video_file_id,

                    caption=alert_text,

                    parse_mode="HTML",
                )

                print(
                    f"✅ Initial animation alert sent "
                    f"to {LIVE_CHANNEL}"
                )

            else:

                await context.bot.send_video(

                    chat_id=LIVE_CHANNEL,

                    video=video_file_id,

                    caption=alert_text,

                    parse_mode="HTML",
                )

                print(
                    f"✅ Initial VIDEO alert sent "
                    f"to {LIVE_CHANNEL}"
                )

        else:

            await context.bot.send_message(

                chat_id=LIVE_CHANNEL,

                text=alert_text,

                parse_mode="HTML",

                disable_web_page_preview=True,
            )

            print(
                f"✅ Initial text alert sent "
                f"to {LIVE_CHANNEL}"
            )

    except Exception as error:

        print(
            "❌ Could not send initial alert: "
            f"{type(error).__name__}: {error}"
        )

    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )


# =========================================================
# BUTTON HANDLER
# =========================================================

async def button_handler( update: Update, context: ContextTypes.DEFAULT_TYPE ):

    query = update.callback_query

    data = query.data

    # -----------------------------------------------------
    # LEADERBOARD
    # -----------------------------------------------------

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
                "could not be loaded.",

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

    # -----------------------------------------------------
    # TRACK CHANNEL
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # BOT ADMIN CHECK
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # SEARCH KOL
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # BACK
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # ACCEPT
    # -----------------------------------------------------

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
                "Existing verification check error: "
                f"{error}"
            )

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

        try:

            await context.bot.send_message(

                chat_id=user_id,

                text=(

                    "✅ Channel Approved!\n\n"

                    f"📡 Channel: {channel}\n\n"

                    "Your channel has been verified "
                    "on KOLPulse.\n\n"

                    "🔎 New calls will now be "
                    "automatically tracked."
                ),
            )

        except Exception as error:

            print(
                f"Could not notify user: {error}"
            )

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

    # -----------------------------------------------------
    # REJECT
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # TOP KOLS
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # SUPPORT
    # -----------------------------------------------------

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

    await query.answer()

    await query.edit_message_text(

        "⚠️ Unknown option.",

        reply_markup=main_menu(),
    )


# =========================================================
# VERIFY BOT ADMIN
# =========================================================

async def verify_bot_is_channel_admin( context, channel ):

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

async def channel_message( update: Update, context: ContextTypes.DEFAULT_TYPE ):

    if not update.message:

        return

    if not update.message.text:

        return

    message_text = (
        update.message.text.strip()
    )

    # -----------------------------------------------------
    # SEARCH KOL
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # TRACK CHANNEL
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # VERIFY ADMIN
    # -----------------------------------------------------

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

    print(
        f"✅ KOLPulse bot is Admin in "
        f"{channel}"
    )

    # -----------------------------------------------------
    # REQUEST STATUS
    # -----------------------------------------------------

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
            "Please try again.",

            reply_markup=main_menu(),
        )

        return

    # -----------------------------------------------------
    # APPROVED
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # PENDING
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # SAVE PENDING
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # ADMIN GROUP NOTIFICATION
    # -----------------------------------------------------

    notification = (

        "📡 NEW CHANNEL TRACKING REQUEST\n\n"

        f"👤 User: {user_display}\n"

        f"🆔 Telegram ID: {user_id}\n\n"

        f"📺 Channel: {channel}\n"

        f"🔗 Link: "
        f"https://t.me/"
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

    # -----------------------------------------------------
    # CONFIRMATION
    # -----------------------------------------------------

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

    init_database()

    ensure_tracking_requests_table()

    ensure_call_tracking_columns()

    print(
        "🚀 KOLPulse Bot starting..."
    )

    print(
        f"📡 Admin Group: "
        f"{GROUP_CHAT_ID}"
    )

    print(
        "📡 Monitoring: "
        "ALL VERIFIED / APPROVED CHANNELS"
    )

    print(
        "📡 Raven-only restriction: DISABLED"
    )

    print(
        f"🤖 Bot: "
        f"{BOT_USERNAME}"
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
        "📈 DexScreener live MC tracking enabled."
    )

    print(
        "🚀 Pump milestone alerts enabled from "
        f"{MIN_PUMP_MILESTONE}X → 1000X+."
    )

    print(
        "🔴 Dump alerts DISABLED."
    )

    print(
        "🎥 KOL video forwarding enabled."
    )

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

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

    app.add_handler(
        CommandHandler(
            "setmilestone",
            setmilestone
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    app.add_handler(
        MessageHandler(
            filters.UpdateType.CHANNEL_POST,
            channel_post_handler,
        )
    )

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
