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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["waiting_for_channel"] = False

    await update.message.reply_text(
        "⚡ Welcome to KOLPulse!\n\n"
        "Track Telegram KOL calls, performance, ROI and leaderboards.\n\n"
        "Choose an option below:",
        reply_markup=main_menu(),
    )


# =========================================================
# GROUP ID
# =========================================================

async def groupid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    await update.message.reply_text(
        "🆔 Chat ID:\n\n"
        f"`{chat.id}`",
        parse_mode="Markdown",
    )


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

        text += (
            f"🟢 {project_name}\n"
            f"👤 {kol_username}\n"
            f"💰 Call MC: ${call_mc:,.0f}\n"
            f"📈 Current MC: ${current_mc:,.0f}\n"
            f"🚀 Multiplier: {multiplier:.2f}x\n"
            f"⏱️ {call_time or 'N/A'}\n\n"
        )

        if original_call_link:
            text += f"🔎 Call: {original_call_link}\n"

        if kol_link:
            text += f"💍 KOL: {kol_link}\n"

        if project_link:
            text += f"🪙 Project: {project_link}\n"

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

    print("🚀 KOLPulse Bot starting...")
    print(f"📡 Admin Group: {GROUP_CHAT_ID}")
    print("🗄️ Database initialized.")

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("groupid", groupid)
    )

    app.add_handler(
        CallbackQueryHandler(button_handler)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            channel_message,
        )
    )

    print("✅ KOLPulse Bot is now running...")
    print("⏳ Polling Telegram...")

    app.run_polling(
        drop_pending_updates=False
    )


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":
    main()
