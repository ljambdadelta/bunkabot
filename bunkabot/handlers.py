from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters

from bunkabot.config import *

import asyncio, re, tempfile, os, logging, html
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
     r"(https?://(?:www\.)?"
     r"(?:(?:youtube\.com/watch\?v=|youtu\.be/)"
     r"(?P<id>[\w-]{11})"          # 11-char video id – kept as group "id"
     r"[^\s]*)                     # grab the rest of the query string"
     r")",
     re.IGNORECASE,
)

# ─── Downloader (runs in thread, returns path) ──────────────────────────
def _dl_youtube(url: str) -> str:
    opts = {
        # template must live in a dict 👉
        "outtmpl": {"default": "%(title).80s.%(ext)s"},
        "format": (
            "bestvideo[ext=mp4][filesize<=50M]+bestaudio[ext=m4a]"
            "/best[ext=mp4][filesize<=50M]/best[filesize<=50M]"
        ),
        "noplaylist": True,
        "quiet": True,
    }

    with YoutubeDL(opts) as ydl, tempfile.TemporaryDirectory() as tmp:
        # 1️⃣ probe (to fail fast if URL is bad)
        info = ydl.extract_info(url, download=False)

        # 2️⃣ tell yt-dlp to dump into our temp dir
        ydl.params["outtmpl"] = {"default": os.path.join(tmp, "%(id)s.%(ext)s")}
        result = ydl.extract_info(url, download=True)

        # 3️⃣ resolve actual downloaded file name
        filename = ydl.prepare_filename(result)

        # 4️⃣ move to /tmp so it survives after the TemporaryDirectory closes
        final_path = os.path.join("/tmp", os.path.basename(filename))
        os.rename(filename, final_path)
        return {
            "path": final_path,
            "title": info.get("title", "Untitled"),
            "thumb_url": info.get("thumbnail"),  # may be None
        }

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
        info = await loop.run_in_executor(None, partial(_dl_youtube, url))
        video_path = info["path"]
        video_title = info["title"]
    except Exception as exc:
        logging.exception("yt-dlp failed:")
        await status_msg.edit_text(f"❌ Couldn’t download video: {exc}")
        return

    # --- Build caption in HTML ---
    caption = (
        f'<a href="{html.escape(url)}">ORIGINAL</a>\n'
        f'{"─" * 12}\n'
        f'{html.escape(video_title)}\n'
        f'{"─" * 12}'
    )

    if rest:
        caption += f"\n{html.escape(rest)}"

    thumb_file = None
    if info["thumb_url"]:
        # tiny helper – synchronous is fine inside the thread pool
        import urllib.request, pathlib, os, tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as fh:
            urllib.request.urlretrieve(info["thumb_url"], fh.name)
            # Telegram Bot API ≥ 6.7: thumbnail max 200 kB, JPG/PNG, ≤ 320×320.
            thumb_file = fh.name

    try:
        await ctx.bot.send_video(
            chat_id = CHANNEL_ID,
            video = open(video_path, "rb"),
            thumbnail=open(thumb_file, "rb") if thumb_file else None,
            caption = caption,
            parse_mode = constants.ParseMode.HTML,
        )
    finally:
        for f in (video_path, thumb_file):
            if f:
                try:
                    os.remove(f)
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
    app.add_handler(MessageHandler(filters.Regex(YOUTUBE_RE), youtube_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
