from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters

from bunkabot.config import ALLOWED_USERS


def _authorised(user_id: int) -> bool:
    return not ALLOWED_USERS or user_id in ALLOWED_USERS


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorised(update.effective_user.id):
        return  # silently drop
    await update.message.reply_text("👋 Hi! I'm alive (via webhook).")


async def echo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorised(update.effective_user.id):
        return
    await update.message.reply_text(update.message.text)


def register(dp):
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))