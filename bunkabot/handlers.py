from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters

from bunkabot.config import *

import asyncio, re, tempfile, os, logging, html, pathlib, urllib.request
from PIL import Image
from functools import partial
from telegram import Update, constants
from telegram.ext import (
    ContextTypes,
    MessageHandler,
    filters,
    CommandHandler,
)
from yt_dlp import YoutubeDL

# New, looser pattern
YOUTUBE_RE = re.compile(
    r"(?i)"                                   # case-insensitive
    r"(?P<url>"                               # whole URL → group “url”
      r"(?:https?://)?"                       # scheme – optional
      r"(?:www\.)?"                           # www. – optional
      r"(?:"
        r"(?:youtube\.com/"
           r"(?:watch\?v=|shorts/)"           #  ▶ watch?v=… | shorts/…
        r"|youtu\.be/)"                       #  ▶ youtu.be/…
      r")"
      r"(?P<id>[A-Za-z0-9_-]{11})"            # 11-char ID
      r"[^\s]*"                               # anything up to next space
    r")",
)

# ----------------------------------------------------------------------
def _shrink_thumbnail(url: str) -> str | None:
    """
    Download *url*, ensure <= 320×320 and <= 200 kB.
    Returns a local file-path or None if anything fails.
    """
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = resp.read()
    except Exception:
        return None

    # Early exit: already compliant?
    from io import BytesIO
    img = Image.open(BytesIO(data)).convert("RGB")
    if len(data) <= 200_000 and max(img.size) <= 320:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        img.save(tmp, format="JPEG", quality=90, optimize=True)
        tmp.close()
        return tmp.name

    # Otherwise re-encode with Pillow
    try:
        from io import BytesIO
        img = Image.open(BytesIO(data)).convert("RGB")

        img.thumbnail((319, 319))     # in-place, keeps aspect ratio

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        # Start at quality = 85, drop until we’re <200 kB (floor 50)
        for q in range(85, 29, -5):
            tmp.seek(0)
            img.save(tmp, format="JPEG", quality=q, optimize=True)
            if tmp.tell() <= 200_000:
                tmp.close()
                return tmp.name
        tmp.close()
    except Exception:
        pass
    return None


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

    m = ctx.matches[0]          # first (and only) regex that fired
    url = m.group("url")

    rest = YOUTUBE_RE.sub("", update.message.text).strip()

    status_msg = await update.message.reply_text("📥 Downloading…")

    loop = asyncio.get_running_loop()
    try:
        info = await loop.run_in_executor(None, partial(_dl_youtube, url))
        video_path = info["path"]
        video_title = info["title"]
        # prepare compliant thumbnail (runs in event-loop, fast)
        thumb_path  = _shrink_thumbnail(info["thumb_url"]) if info["thumb_url"] else None
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
        if thumb_path:
            from PIL import Image
            s = os.path.getsize(thumb_path)
            w, h = Image.open(thumb_path).size
            logging.info("Thumbnail: %d B  %dx%d", s, w, h)
        await ctx.bot.send_video(
            chat_id = CHANNEL_ID,
            video = open(video_path, "rb"),
            thumbnail=open(thumb_path, "rb") if thumb_path else None,
            caption = caption,
            parse_mode = constants.ParseMode.HTML,
        )
    finally:
        for f in (video_path, thumb_path):
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
