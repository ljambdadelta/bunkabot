from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters

from bunkabot.config import *

import asyncio, re, tempfile, os, logging
from functools import partial
from telegram import Update, constants
from telegram.ext import (
    ContextTypes,
    MessageHandler,
    filters,
    CommandHandler,
)
from yt_dlp import YoutubeDL

YOUTUBE_RE = re.compile(
    r"(https?://(?:www\.)?(?:youtube\.com/watch\?v=[\w-]{11}|youtu\.be/[\w-]{11}))",
    re.IGNORECASE,
)

# ─── Downloader (runs in thread, returns path) ──────────────────────────
def _dl_youtube(url: str) -> str:
    opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": "%(title).80s.%(ext)s",
        "noplaylist": True,
        # Keep files reasonable for Telegram (≤ 50 MB for most users)
        "filesize_limit": 50 * 1024 * 1024,
        "quiet": True,
    }
    with YoutubeDL(opts) as ydl, tempfile.TemporaryDirectory() as tmp:
        info = ydl.extract_info(url, download=False)
        # overwrite output template so we always end in tmp dir
        ydl.params["outtmpl"] = os.path.join(tmp, "%(id)s.%(ext)s")
        result = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(result)
        # move file outside tmp (Telegram will read after ctx switch)
        final_path = os.path.join("/tmp", os.path.basename(filename))
        os.rename(filename, final_path)
        return final_path  # caller must unlink

# ─── New async handler ──────────────────────────────────────────────────
async def youtube_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    m = YOUTUBE_RE.search(update.message.text)
    if not m:
        return

    url = m.group(1)
    rest = YOUTUBE_RE.sub("", update.message.text).strip()

    status_msg = await update.message.reply_text("📥 Downloading…")

    loop = asyncio.get_running_loop()
    try:
        video_path = await loop.run_in_executor(None, partial(_dl_youtube, url))
    except Exception as exc:
        logging.exception("yt-dlp failed:")
        await status_msg.edit_text(f"❌ Couldn’t download video: {exc}")
        return

    # Build caption: [ORIGINAL](url)\n────────────\nrest
    caption = f"[ORIGINAL]({url})\n" + "─" * 12
    if rest:
        caption += f"\n{rest}"

    try:
        await ctx.bot.send_video(
            chat_id = CHANNEL_ID,
            video = open(video_path, "rb"),
            caption = caption,
            parse_mode = constants.ParseMode.MARKDOWN,
        )
    finally:
        try:
            os.remove(video_path)
        except FileNotFoundError:
            pass


def _authorised(user_id: int) -> bool:
    return not ALLOWED_USERS or user_id in ALLOWED_USERS


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorised(update.effective_user.id):
        return  # silently drop
    await update.message.reply_text("Hello there")


async def echo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorised(update.effective_user.id):
        return
    await update.message.reply_text(update.message.text)

# ─── wire it up ─────────────────────────────────────────────────────────
def register(app):
    # existing /start + echo → keep
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & YOUTUBE_RE, youtube_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
