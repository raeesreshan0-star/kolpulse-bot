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
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "")


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


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["waiting_for_channel"] = False

    await update.message.reply_text(
        "⚡ Welcome to KOLPulse!\n\n"
        "Track Telegram KOL calls, performance, ROI and leaderboards.\n\n"
        "Choose an option below:",
        reply_markup=main_menu(),
    )


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


async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
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

    # Convert Telegram link to username
    if "t.me/" in channel:

        channel = channel.split("t.me/", 1)[1]
        channel = channel.split("?", 1)[0]
        channel = channel.split("/", 1)[0]

        if not channel.startswith("@"):
            channel = "@" + channel

    # Convert plain username to @username
    elif not channel.startswith("@"):
        channel = "@" + channel

    context.user_data["waiting_for_channel"] = False

    # User information
    user = update.effective_user

    if user.username:
        user_display = f"@{user.username}"
    else:
        user_display = user.full_name

    user_id = user.id

    # Current time
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Send confirmation to user
    await update.message.reply_text(
        "✅ Channel received!\n\n"
        f"📡 Channel: {channel}\n\n"
        "Your tracking request has been submitted to KOLPulse.",
        reply_markup=main_menu(),
    )

    # Send notification to admin group
    if GROUP_CHAT_ID:

        notification = (
            "📡 NEW CHANNEL TRACKING REQUEST\n\n"
            f"👤 User: {user_display}\n"
            f"🆔 Telegram ID: {user_id}\n\n"
            f"📺 Channel: {channel}\n"
            f"🔗 Link: https://t.me/{channel.lstrip('@')}\n\n"
            f"⏰ Time: {current_time}\n\n"
            "#KOLPulse"
        )

        try:
            await context.bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=notification,
            )

        except Exception as error:
            print(
                f"Could not send group notification: {error}"
            )


def main():

    if not BOT_TOKEN:
        raise ValueError(
            "BOT_TOKEN is not configured."
        )

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands
    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("groupid", groupid)
    )

    # Buttons
    app.add_handler(
        CallbackQueryHandler(button_handler)
    )

    # Channel username/link messages
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            channel_message,
        )
    )

    print("KOLPulse bot is running...")

    app.run_polling()


if __name__ == "__main__":
    main() 
