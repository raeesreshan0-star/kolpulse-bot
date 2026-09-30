import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
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
    await update.message.reply_text(
        "⚡ Welcome to KOLPulse!\n\n"
        "Track Telegram KOL calls, performance, ROI and leaderboards.\n\n"
        "Choose an option below:",
        reply_markup=main_menu(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    responses = {
        "live_calls": "🔥 Live Calls\n\nLive tracked KOL calls will appear here.",
        "track_channel": "📡 Track My Channel\n\nSend your Telegram channel username to request tracking.",
        "leaderboard": "📊 KOL Leaderboard\n\nLeaderboard data will appear here.",
        "search_kol": "🔎 Search KOL\n\nSearch for a tracked KOL or channel.",
        "performance": "📈 Call Performance\n\nIndividual call performance will appear here.",
        "top_kols": "🏆 Top KOLs\n\nTop performing KOLs will appear here.",
        "about": "ℹ️ KOLPulse\n\nKOLPulse tracks Telegram KOL calls and provides performance, ROI and leaderboard data.",
        "support": "🆘 Support\n\nContact: @ZENITP2P",
    }

    await query.edit_message_text(
        responses.get(query.data, "Unknown option."),
        reply_markup=main_menu(),
    )


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not configured.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("KOLPulse bot is running...")
    app.run_polling()


if name == "main":
    main()
