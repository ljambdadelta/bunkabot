import asyncio, logging
from fastapi import FastAPI, Request, HTTPException, status
from telegram.ext import Application, ApplicationBuilder
from telegram import Update
from .config import BOT_TOKEN, BASE_URL, PORT, WEBHOOK_SECRET
from .handlers import register

logging.basicConfig(level=logging.INFO)

app   = FastAPI()
bot   = ApplicationBuilder().token(BOT_TOKEN).build()
register(bot)                    # wire up /start & echo

@app.on_event("startup")
async def on_startup():
    # 1️⃣  Prepare PTB – creates dispatcher, job queue, etc.
    await bot.initialize()
    await bot.bot.set_webhook(
        url=f"{BASE_URL}/webhook/{WEBHOOK_SECRET}",
        allowed_updates=["message", "edited_message"],
    )

@app.on_event("shutdown")
async def on_shutdown():
    """Gracefully tear PTB down when FastAPI stops."""
    await bot.shutdown()


@app.post(f"/webhook/{{token}}")
async def telegram_webhook(token: str, request: Request):
    """Receive updates from Telegram & hand them to PTB."""
    if token != WEBHOOK_SECRET:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    data = await request.json()
    update: Update = Update.de_json(data, bot.bot)  # low-level object
    await bot.process_update(update)
    return {"ok": True}

# Local launch:  uvicorn bot.main:app --host 0.0.0.0 --port $PORT --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bot.main:app", host="0.0.0.0", port=PORT)