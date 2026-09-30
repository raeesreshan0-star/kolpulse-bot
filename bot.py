import os
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

from database import init_database, get_live_calls


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "").strip()


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
    context: ContextTypes.DEFAULT
