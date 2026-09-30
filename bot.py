import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["waiting_for_channel"] = False

    await update.message.reply_text(
        "⚡ Welcome to KOLPulse!\n\n"
        "Track Telegram KOL calls, performance, ROI and leaderboards.\n\n"
        "Choose an option below:",
        reply_markup=main_menu(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

 if query.data == "track_channel":
    context.user_data["waiting_for_channel"] = True

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
    if query.data == "back_menu":
        context.user_data["waiting_for_channel"] = False

        await query.edit_message_text(
            "⚡ KOLPulse Main Menu\n\n"
            "Choose an option below:",
            reply_markup=main_menu(),
        )
        return

    responses = {
        "live_calls":
            "🔥 Live Calls\n\n"
            "Live tracked KOL calls will appear here.",

        "leaderboard":
            "📊 KOL Leaderboard\n\n"
            "Leaderboard data will appear here.",

        "search_kol":
            "🔎 Search KOL\n\n"
            "Search for a tracked KOL or channel.",

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
        responses.get(query.data, "Unknown option."),
        reply_markup=main_menu(),
    )


async def channel_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.user_data.get("waiting_for_channel"):
        return

    channel = update.message.text.strip()

    # Accept Telegram links
    if "t.me/" in channel:
        channel = channel.split("t.me/")[1]
        channel = channel.split("?")[0]
        channel = channel.split("/")[0]

        if not channel.startswith("@"):
            channel = "@" + channel

    # Accept @
