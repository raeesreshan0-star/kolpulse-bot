import os
from datetime import datetime

from dotenv import load_dotenv
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

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "").strip()


def main_menu():
    keyboard = [
        [
            InlineKeyboardButton("🔥 Live Calls", callback_data="live_calls"),
            InlineKeyboardButton("📡 Track My Channel", callback_data="track_channel"),
        ],
        [
            InlineKeyboardButton("📊 KOL Leaderboard", callback_data="leaderboard"),
            InlineKeyboardButton("🔎 Search KOL", callback_data="search_kol"),
        ],
        [
            InlineKeyboardButton("📈 Call Performance", callback_data="performance"),
            InlineKeyboardButton("🏆 Top KOLs", callback_data="top_kols"),
        ],
        [
            InlineKeyboardButton("ℹ️ About KOLPulse", callback_data="about"),
            InlineKeyboardButton("🆘 Support", callback_data="support"),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def request_buttons(user_id, channel):
    """
    Buttons for admin group.
    """
    callback_channel = channel.lstrip("@")

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Accept",
                callback_data=f"accept:{user_id}:{callback_channel}"
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"reject:{user_id}:{callback_channel}"
            ),
        ]
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["waiting_for_channel"] = False

    await update.message.reply_text(
        "⚡ Welcome to KOLPulse!\n\n"
        "Track Telegram KOL calls, performance, ROI and leaderboards.\n\n"
        "Choose an option below:",
        reply_markup=main_menu(),
    )


async def groupid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    await update.message.reply_text(
        "🆔 Chat ID:\n\n"
        f"`{chat.id}`",
        parse_mode="Markdown",
    )


async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    # =========================
    # ACCEPT REQUEST
    # =========================

    if query.data.startswith("accept:"):

        parts = query.data.split(":", 2)

        if len(parts) != 3:
            await query.answer(
                "Invalid request.",
                show_alert=True
            )
            return

        user_id = int(parts[1])
        channel = "@" + parts[2]

        # Only allow admin group
        if str(query.message.chat.id) != GROUP_CHAT_ID:
            await query.answer(
                "Not authorized.",
                show_alert=True
            )
            return

        # Check if button clicker is admin
        try:
            member = await context.bot.get_chat_member(
                chat_id=query.message.chat.id,
                user_id=query.from_user.id,
            )

            if member.status not in ["administrator", "creator"]:
                await query.answer(
                    "Only group admins can approve requests.",
                    show_alert=True
                )
                return

        except Exception as error:
            print(f"Admin check error: {error}")

        # Notify requester
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "✅ Channel Approved!\n\n"
                    f"📡 Channel: {channel}\n\n"
                    "Your channel tracking request has been "
                    "approved by KOLPulse.\n\n"
                    "📊 Tracking setup will be activated next."
                ),
            )

            user_notified = True

        except Exception as error:
            print(f"Could not notify user: {error}")
            user_notified = False

        # Update group message
        status_text = (
            "✅ APPROVED\n
