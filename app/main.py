import asyncio
from fastapi import FastAPI
from contextlib import asynccontextmanager
import uvicorn
from app.utils.logger import setup_logger
from app.config import settings
from app.bot.telegram_bot import setup_telegram_app

logger = setup_logger(__name__)

# Wir speichern die Telegram Application global, um sie sauber zu starten und stoppen
telegram_app = setup_telegram_app()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starte FastAPI Backend und Telegram Bot (Long Polling)...")
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling()
    yield
    # Shutdown
    logger.info("Stoppe Telegram Bot...")
    await telegram_app.updater.stop()
    await telegram_app.stop()
    await telegram_app.shutdown()

# Eine minimale FastAPI App. Wird auf Railway benötigt, damit der Healthcheck Port 8000/3000 findet.
app = FastAPI(lifespan=lifespan)

@app.get("/")
def health_check():
    return {"status": "ok", "service": "visioskin-accounting-agent"}

if __name__ == "__main__":
    # Startet den Uvicorn Server, welcher über lifespan auch den Bot startet.
    import os
    port = int(os.environ.get("PORT", 3000))
    logger.info(f"Starte Server auf Port {port}")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
