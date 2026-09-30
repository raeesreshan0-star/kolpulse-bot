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


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "").strip()

LIVE_CHANNEL = "@KOLPulse_Live"
RAVEN_CHANNEL = "@CRYPTO_RAVEN_CALL"
BOT_LINK = "https://t.me/KOLPulse_Live_bot"


# =========================================================
# CHANNEL REQUEST STATUS
# =========================================================

def normalize_channel(channel):
    """Return a clean Telegram channel username."""
    channel = (channel or "").strip()

    if "t.me/" in channel.lower():
        channel = channel.split("t.me/", 1)[1]
        channel = channel.split("?", 1)[0]
        channel = channel.split("/", 1)[0]

    if not channel.startswith("@"):
        channel = "@" + channel

    return channel


def ensure_tracking_requests_table():
    """
    Stores Track My Channel requests so the bot can distinguish:
    PENDING -> APPROVED -> REJECTED.

    This is separate from verified_channels so existing database.py
    does not need to be changed just to track pending requests.
    """
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
    """Return pending/approved/rejected/None."""
    channel = normalize_channel(channel)
    clean = channel.lstrip("@").lower()

    # Approved channels are determined by verified_channels.
    try:
        verified = get_verified_channel(channel)

        if verified:
            return "approved"

    except Exception as error:
        print(
            f"⚠️ get_verified_channel check failed: "
            f"{type(error).__name__}: {error}"
        )

    # Pending/rejected state is stored in our request table.
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


def save_pending_request(channel, user_id):
    """Create or refresh a pending request."""
    channel = normalize_channel(channel)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    cursor = conn.cursor()

    # If a rejected request exists, allow a fresh request.
    cursor.execute("""
        SELECT id, status
        FROM channel_tracking_requests
        WHERE LOWER(REPLACE(channel_username, '@', '')) = ?
        ORDER BY id DESC
        LIMIT 1
    """, (channel.lstrip("@").lower(),))

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
        """, (user_id, now, request_id))

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


def update_request_status(channel, status):
    """Update the local request record."""
    channel = normalize_channel(channel)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
# =========================================================

def main_menu():

    keyboard = [
        [
            InlineKeyboardButton(
                "🔥 Live Calls",
                callback_data="live_calls"
            ),
            InlineKeyboardButton(
                "📡 Track My Channel",
                callback_data="track_channel"
            ),
        ],
        [
            InlineKeyboardButton(
                "📊 KOL Leaderboard",
                callback_data="leaderboard"
            ),
            InlineKeyboardButton(
                "🔎 Search KOL",
                callback_data="search_kol"
            ),
        ],
        [
            InlineKeyboardButton(
                "📈 Call Performance",
                callback_data="performance"
            ),
            InlineKeyboardButton(
                "🏆 Top KOLs",
                callback_data="top_kols"
            ),
        ],
        [
            InlineKeyboardButton(
                "ℹ️ About KOLPulse",
                callback_data="about"
            ),
            InlineKeyboardButton(
                "🆘 Support",
                callback_data="support"
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# ACCEPT / REJECT BUTTONS
# =========================================================

def request_buttons(user_id, channel):

    channel_name = channel.lstrip("@")

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Accept",
                callback_data=f"accept:{user_id}:{channel_name}"
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"reject:{user_id}:{channel_name}"
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

    context.user_data["waiting_for_channel"] = False
    context.user_data["waiting_for_kol_search"] = False

    await update.message.reply_text(
        "⚡ Welcome to KOLPulse!\n\n"
        "Track Telegram KOL calls, performance, ROI "
        "and leaderboards.\n\n"
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
        return f"{value / 1_000_000_000:.1f}B"

    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"

    if value >= 1_000:
        return f"{value / 1_000:.1f}K"

    return f"{value:,.0f}"


# =========================================================
# TOKEN SYMBOL DETECTION
# =========================================================

def detect_token_symbol(
    text,
    project_name,
    contract
):

    match = re.search(
        r"\$([A-Za-z][A-Za-z0-9_]*)",
        text
    )

    if match:
        return "$" + match.group(1)

    match = re.search(
        r"\$([A-Za-z][A-Za-z0-9_]*)",
        project_name or ""
    )

    if match:
        return "$" + match.group(1)

    if project_name:

        clean_name = (
            project_name
            .split("|")[0]
            .strip()
        )

        if clean_name:
            return "$" + clean_name.split()[0]

    return "$TOKEN"


# =========================================================
# LIVE CALLS
# =========================================================

async def show_live_calls(query):

    calls = get_live_calls()

    if not calls:

        await query.edit_message_text(
            "🔥 Live Calls\n\n"
            "No live calls are available yet.\n\n"
            "📡 KOLPulse is ready to track new calls.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Back to Menu",
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
                f"🔎 Call: {original_call_link}\n"
            )

        if kol_link:
            text += (
                f"💍 KOL: {kol_link}\n"
            )

        if project_link:
            text += (
                f"🪙 Project: {project_link}\n"
            )

        text += "\n"

    await query.edit_message_text(
        text,
        disable_web_page_preview=False,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔄 Refresh",
                    callback_data="live_calls"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Back to Menu",
                    callback_data="back_menu"
                )
            ]
        ]),
    )


# =========================================================
# KOL LEADERBOARD DATABASE
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
            "Verified KOLs will appear here after "
            "their calls are tracked.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔄 Refresh",
                        callback_data="leaderboard"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Back to Menu",
                        callback_data="back_menu"
                    )
                ]
            ]),
        )

        return

    text = "📊 <b>KOL LEADERBOARD</b>\n\n"

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    for index, row in enumerate(leaderboard):

        channel_username = row[0]
        total_calls = row[1] or 0
        two_x_calls = row[2] or 0
        best_multiplier = row[3] or 0

        if index < 3:
            rank = medals[index]
        else:
            rank = f"<b>#{index + 1}</b>"

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
            f"🔥 Best: {best_multiplier:.2f}x\n\n"
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
                    "🔄 Refresh",
                    callback_data="leaderboard"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Back to Menu",
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
        "Send the Telegram KOL channel username or link.\n\n"
        "Example:\n"
        "@CRYPTO_RAVEN_CALL\n\n"
        "or\n"
        "https://t.me/CRYPTO_RAVEN_CALL",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⬅️ Back to Menu",
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

    verified = get_verified_channel(channel)

    if not verified:

        await update.message.reply_text(
            "❌ KOL Not Verified\n\n"
            f"{channel} isn't verified on KOLPulse yet.\n\n"
            "Please verify the channel first using\n"
            "📡 Track My Channel.",
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
            f"💰 Call MC: {call_mc_text}\n"
            f"📈 Current MC: {current_mc_text}\n"
            f"🚀 Multiplier: {multiplier_text}\n"
            f"⏱️ {call_time or 'N/A'}\n"
        )

        if original_call_link:
            text += (
                f"🔎 Call: {original_call_link}\n"
            )

        if project_link:
            text += (
                f"🪙 Project: {project_link}\n"
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

async def channel_post_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

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

    channel = f"@{chat.username}"

    print(
        f"📨 New channel post received from {channel}"
    )

    text = (
        message.text
        or message.caption
        or ""
    )

    if not text:

        print(
            f"⏭️ Empty post ignored from {channel}"
        )

        return

    if channel.lower() != RAVEN_CHANNEL.lower():

        print(
            f"⏭️ Channel is not configured for tracking: "
            f"{channel}"
        )

        return

    verified = get_verified_channel(channel)

    if not verified:

        print(
            f"⏭️ Ignored unverified channel: {channel}"
        )

        return

    print(
        f"✅ Verified KOL detected: {channel}"
    )

    contract = None

    for line in text.splitlines():

        if "contract:" in line.lower():

            contract = line.split(
                ":",
                1
            )[1].strip()

            break

    if not contract:

        print(
            f"⏭️ No Contract found in {channel} post."
        )

        return

    call_mc = None

    for line in text.splitlines():

        if "market cap:" in line.lower():

            mc_text = line.split(
                ":",
                1
            )[1].strip()

            mc_text = (
                mc_text
                .replace("$", "")
                .replace(",", "")
                .strip()
            )

            try:

                if mc_text.lower().endswith("k"):

                    call_mc = (
                        float(mc_text[:-1])
                        * 1_000
                    )

                elif mc_text.lower().endswith("m"):

                    call_mc = (
                        float(mc_text[:-1])
                        * 1_000_000
                    )

                elif mc_text.lower().endswith("b"):

                    call_mc = (
                        float(mc_text[:-1])
                        * 1_000_000_000
                    )

                else:

                    call_mc = float(mc_text)

            except ValueError:

                call_mc = None

            break

    if call_mc is None:

        print(
            f"⏭️ Could not read Market Cap "
            f"from {channel} post."
        )

        return

    project_name = None

    for line in text.splitlines():

        if line.lower().startswith("name:"):

            project_name = line.split(
                ":",
                1
            )[1].strip()

            break

    if not project_name:

        project_name = contract[:12]

    token_symbol = detect_token_symbol(
        text,
        project_name,
        contract
    )

    original_call_link = (
        f"https://t.me/"
        f"{chat.username}/"
        f"{message.message_id}"
    )

    kol_link = (
        f"https://t.me/"
        f"{chat.username}"
    )

    try:

        call_id = add_call(
            kol_username=channel,
            project_name=project_name,
            kol_link=kol_link,
            project_link=None,
            original_call_link=original_call_link,
            call_mc=call_mc,
            current_mc=call_mc,
            multiplier=1,
            call_time=datetime.utcnow().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            video_file_id=None,
            status="live",
        )

        print(
            "✅ CALL DETECTED\n"
            f"   KOL: {channel}\n"
            f"   Project: {project_name}\n"
            f"   Token: {token_symbol}\n"
            f"   Contract: {contract}\n"
            f"   Call MC: ${call_mc:,.0f}\n"
            f"   Call ID: {call_id}"
        )

    except Exception as error:

        print(
            f"❌ Could not save detected call: "
            f"{type(error).__name__}: {error}"
        )

        return

    try:

        safe_channel = html.escape(channel)
        safe_token = html.escape(token_symbol)
        safe_contract = html.escape(contract)

        mc_display = format_market_cap(
            call_mc
        )

        alert_text = (
            f'🔮 <a href="{kol_link}">'
            f'{safe_channel}</a> Dropped a Call 🔮\n\n'

            f"🔮 Token Symbol   🔮 {safe_token}\n"
            f"🔮 Current MC     🔮 {mc_display}\n"
            f"🔮 Chain Symbol   🔮 RH\n\n"

            "We've started tracking it and will continue to "
            "send performance alerts as the token progresses. "
            "Stay tuned!\n\n"

            f"Ca: <code>{safe_contract}</code>\n\n"

            f'🔮 <a href="{original_call_link}">CALL</a>    '
            f'🔮 <a href="{kol_link}">KOL</a>    '
            f'🔮 <a href="{BOT_LINK}">BOT</a>'
        )

        await context.bot.send_message(
            chat_id=LIVE_CHANNEL,
            text=alert_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

        print(
            "✅ Formatted alert sent to KOLPulse Live."
        )

    except Exception as error:

        print(
            "❌ Could not send formatted alert: "
            f"{type(error).__name__}: {error}"
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
    # LIVE CALLS
    # =====================================================

    if data == "live_calls":

        await query.answer()

        try:

            await show_live_calls(query)

        except Exception as error:

            print(
                f"Live Calls error: {error}"
            )

            await query.edit_message_text(
                "⚠️ Live Calls could not be loaded.\n\n"
                "Please try again.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "⬅️ Back to Menu",
                            callback_data="back_menu"
                        )
                    ]
                ]),
            )

        return

    # =====================================================
    # KOL LEADERBOARD
    # =====================================================

    if data == "leaderboard":

        await query.answer()

        try:

            await show_kol_leaderboard(query)

        except Exception as error:

            print(
                f"Leaderboard error: {type(error).__name__}: {error}"
            )

            await query.edit_message_text(
                "⚠️ KOL Leaderboard could not be loaded.\n\n"
                "Please try again.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "⬅️ Back to Menu",
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

        context.user_data["waiting_for_channel"] = True
        context.user_data["waiting_for_kol_search"] = False

        await query.edit_message_text(
            "📡 Track My Channel\n\n"
            "Send your Telegram channel username.\n\n"
            "Example:\n"
            "@MyCryptoChannel\n\n"
            "Make sure the channel username is correct.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Back to Menu",
                        callback_data="back_menu"
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

        context.user_data["waiting_for_channel"] = False
        context.user_data["waiting_for_kol_search"] = True

        await search_kol(query)

        return

    # =====================================================
    # BACK TO MENU
    # =====================================================

    if data == "back_menu":

        await query.answer()

        context.user_data["waiting_for_channel"] = False
        context.user_data["waiting_for_kol_search"] = False

        await query.edit_message_text(
            "⚡ KOLPulse Main Menu\n\n"
            "Choose an option below:",
            reply_markup=main_menu(),
        )

        return

    # =====================================================
    # ACCEPT REQUEST
    # =====================================================

    if data.startswith("accept:"):

        await query.answer()

        parts = data.split(":", 2)

        if len(parts) != 3:
            return

        try:

            user_id = int(parts[1])

        except ValueError:

            return

        channel = normalize_channel(parts[2])

        if str(query.message.chat.id) != GROUP_CHAT_ID:

            await query.answer(
                "Not authorized.",
                show_alert=True
            )

            return

        try:

            member = await context.bot.get_chat_member(
                chat_id=query.message.chat.id,
                user_id=query.from_user.id,
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

        # Prevent duplicate approval.
        try:

            existing_verified = get_verified_channel(channel)

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
                f"Existing verification check error: {error}"
            )

        # =================================================
        # SAVE VERIFIED CHANNEL
        # =================================================

        try:

            verified_at = add_verified_channel(
                channel_username=channel,
                user_id=user_id,
            )

            update_request_status(
                channel,
                "approved"
            )

            print(
                f"✅ Verified channel saved: "
                f"{channel} at {verified_at}"
            )

        except Exception as error:

            print(
                f"❌ Could not save verified channel: "
                f"{type(error).__name__}: {error}"
            )

            await query.answer(
                "Could not save verification.",
                show_alert=True
            )

            return

        # =================================================
        # NOTIFY REQUESTER
        # =================================================

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "✅ Channel Approved!\n\n"
                    f"📡 Channel: {channel}\n\n"
                    "Your channel has been verified on "
                    "KOLPulse.\n\n"
                    "🔎 Your KOL results can now be tracked."
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
                f"Could not update group message: {error}"
            )

        return

    # =====================================================
    # REJECT REQUEST
    # =====================================================

    if data.startswith("reject:"):

        await query.answer()

        parts = data.split(":", 2)

        if len(parts) != 3:
            return

        try:

            user_id = int(parts[1])

        except ValueError:

            return

        channel = normalize_channel(parts[2])

        if str(query.message.chat.id) != GROUP_CHAT_ID:

            await query.answer(
                "Not authorized.",
                show_alert=True
            )

            return

        try:

            member = await context.bot.get_chat_member(
                chat_id=query.message.chat.id,
                user_id=query.from_user.id,
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
                f"Could not update rejected status: {error}"
            )

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "❌ Channel Request Rejected\n\n"
                    f"📡 Channel: {channel}\n\n"
                    "Your tracking request was rejected by KOLPulse.\n\n"
                    "You can submit the channel again if needed."
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
                f"Could not update group message: {error}"
            )

        return

    # =====================================================
    # OTHER MENU OPTIONS
    # =====================================================

    await query.answer()

    responses = {

        "performance":
            "📈 Call Performance\n\n"
            "Individual call performance will appear here.",

        "top_kols":
            "🏆 Top KOLs\n\n"
            "Top performing KOLs will appear here.",

        "about":
            "ℹ️ KOLPulse\n\n"
            "KOLPulse tracks Telegram KOL calls and provides "
            "performance, ROI and leaderboard data.",

        "support":
            "🆘 Support\n\n"
            "Contact: @ZENITP2P",
    }

    await query.edit_message_text(
        responses.get(
            data,
            "Unknown option."
        ),
        reply_markup=main_menu(),
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

    message_text = update.message.text.strip()

    # =====================================================
    # SEARCH KOL
    # =====================================================

    if context.user_data.get(
        "waiting_for_kol_search"
    ):

        channel = normalize_channel(message_text)

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

    channel = normalize_channel(message_text)

    # Stop waiting immediately.
    context.user_data[
        "waiting_for_channel"
    ] = False

    # =====================================================
    # CHECK CHANNEL STATUS BEFORE SENDING ADMIN REQUEST
    # =====================================================

    try:

        status = get_request_status(channel)

    except Exception as error:

        print(
            f"❌ Channel status check failed: "
            f"{type(error).__name__}: {error}"
        )

        await update.message.reply_text(
            "⚠️ Could not check your channel status.\n\n"
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
            "Your channel is already verified on KOLPulse.\n\n"
            "🔎 Your KOL results can already be tracked.",
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
            "Your tracking request is already waiting "
            "for admin approval.\n\n"
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
    # SAVE AS PENDING BEFORE NOTIFYING ADMIN
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
                "Your tracking request is already waiting "
                "for admin approval.",
                reply_markup=main_menu(),
            )

            return

    except Exception as error:

        print(
            f"❌ Could not save pending request: "
            f"{type(error).__name__}: {error}"
        )

        await update.message.reply_text(
            "⚠️ Could not create your tracking request.\n\n"
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
                "✅ Group notification sent successfully."
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
    # IF GROUP FAILED, KEEP REQUEST PENDING BUT TELL USER
    # =====================================================

    if group_sent:

        confirmation = (
            "✅ Channel received!\n\n"
            f"📡 Channel: {channel}\n\n"
            "Your tracking request has been submitted "
            "to KOLPulse.\n\n"
            "⏳ Waiting for admin approval."
        )

    else:

        confirmation = (
            "⚠️ Channel received!\n\n"
            f"📡 Channel: {channel}\n\n"
            "Your request was saved, but the admin "
            "notification could not be sent.\n\n"
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

    # Create the pending/approved/rejected request table.
    ensure_tracking_requests_table()

    print(
        "🚀 KOLPulse Bot starting..."
    )

    print(
        f"📡 Admin Group: {GROUP_CHAT_ID}"
    )

    print(
        f"📡 Raven Source: {RAVEN_CHANNEL}"
    )

    print(
        f"📡 Live Destination: {LIVE_CHANNEL}"
    )

    print(
        "🗄️ Database initialized."
    )

    print(
        "🗂️ Channel tracking request status system initialized."
    )

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
