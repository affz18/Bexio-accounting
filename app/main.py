"""
Entry Point - startet den Telegram Bot als Long-Polling Worker.

Wird von Railway via Procfile (worker: python -m app.main) gestartet.
Kein HTTP-Server noetig, nur der Bot der Telegram alle paar Sekunden fragt
"gibt's neue Nachrichten?".
"""
import asyncio
import signal
import sys

from app.config import settings
from app.utils import setup_logger
from app.bot import build_application
from app.bexio import bexio as bexio_client
from app.imap_inbox import run_imap_poller


logger = setup_logger(__name__)


async def _main() -> None:
    """Haupt-Loop: Bot starten, Shutdown sauber handhaben."""
    logger.info("=" * 60)
    logger.info("VisioSkin Accounting Agent startet")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Gemini Model: {settings.gemini_model}")
    logger.info(f"Log Level: {settings.log_level}")
    logger.info("=" * 60)
    
    # Telegram Application bauen
    app = build_application()
    
    # Shutdown-Event fuer sauberes Beenden
    stop_event = asyncio.Event()
    
    def _signal_handler():
        logger.info("Shutdown-Signal empfangen")
        stop_event.set()
    
    loop = asyncio.get_running_loop()
    # SIGTERM kommt von Railway bei Deploys
    # SIGINT kommt bei Ctrl+C lokal
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows unterstuetzt das nicht - egal, wir deployen auf Linux
            pass
    
    # Bot starten
    await app.initialize()
    await app.start()
    await app.updater.start_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,  # alte Updates beim Restart ignorieren
    )

    # IMAP-Poller parallel starten (No-Op wenn IMAP_ENABLED=false)
    imap_task = asyncio.create_task(
        run_imap_poller(app, stop_event),
        name="imap_poller",
    )

    logger.info("✅ Bot laeuft. Warte auf Nachrichten…")

    try:
        # Blockiere bis Shutdown-Signal
        await stop_event.wait()
    finally:
        logger.info("Stoppe Bot…")
        try:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
        except Exception as e:
            logger.error(f"Fehler beim Bot-Shutdown: {e}")

        # IMAP-Task sauber beenden
        try:
            await asyncio.wait_for(imap_task, timeout=10)
        except asyncio.TimeoutError:
            logger.warning("IMAP-Task hat Shutdown-Timeout - cancel")
            imap_task.cancel()
        except Exception as e:
            logger.error(f"Fehler beim IMAP-Task-Shutdown: {e}")
        
        # Bexio-Client aufraeumen
        try:
            await bexio_client.close()
        except Exception as e:
            logger.error(f"Fehler beim Bexio-Client-Shutdown: {e}")
        
        logger.info("👋 Bot beendet.")


def main() -> None:
    """Sync-Wrapper fuer asyncio.run() - Entry-Point von Python."""
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        logger.info("Interrupt durch User")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Fataler Fehler: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
