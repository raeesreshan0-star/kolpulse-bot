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
                [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_menu")]
            ]),
        )
        return

    if query.data == "back_menu":
        context.user_data["waiting_for_channel"] = False

        await query.edit_message_text(
            "⚡ KOLPulse Main Menu\n\nChoose an option below:",
            reply_markup=main_menu(),
        )
        return

    responses = {
        "live_calls": "🔥 Live Calls\n\nLive tracked KOL calls will appear here.",
        "leaderboard": "📊 KOL Leaderboard\n\nLeaderboard data will appear here.",
        "search_kol": "🔎 Search KOL\n\nSearch for a tracked KOL or channel.",
        "performance": "📈 Call Performance\n\nIndividual call performance will appear here.",
        "top_kols": "🏆 Top KOLs\n\nTop performing KOLs will appear here.",
        "about": (
            "ℹ️ KOLPulse\n\n"
            "KOLPulse tracks Telegram KOL calls and provides "
            "performance, ROI and leaderboard data."
        ),
        "support": "🆘 Support\n\nContact: @ZENITP2P",
    }

    await query.edit_message_text(
        responses.get(query.data, "Unknown option."),
        reply_markup=main_menu(),
    )


async def channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("waiting_for_channel"):
        return

    username = update.message.text.strip()

    if not username.startswith("@"):
        username = "@" + username

    context.user_data["waiting_for_channel"] = False

    await update.message.reply_text(
        f"✅ Channel received!\n\n"
        f"📡 Channel: {username}\n\n"
        "Your tracking request has been submitted to KOLPulse.\n"
        "Channel verification and tracking setup will be added next.",
        reply_markup=main_menu(),
    )


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not configured.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            channel_message
        )
    )

    print("KOLPulse bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
