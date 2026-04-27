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


async def _shutdown(app, imap_task) -> None:
    """
    Faehrt Bot und alle Hintergrund-Tasks sauber herunter.

    Wird sowohl im Normalfall (stop_event gesetzt) als auch bei
    CancelledError (asyncio.run() bricht ab) aufgerufen.
    asyncio.shield() schuetzt die Cleanup-Coroutinen davor, selbst
    gecancelt zu werden, waehrend der Event-Loop herunterfaehrt.
    """
    logger.info("Stoppe Bot…")

    # Updater zuerst stoppen - beendet das Telegram-Polling sofort,
    # damit kein zweiter Bot-Prozess einen Konflikt ausloest.
    try:
        await asyncio.shield(app.updater.stop())
    except Exception as e:
        logger.error(f"Fehler beim Updater-Stop: {e}")

    try:
        await asyncio.shield(app.stop())
    except Exception as e:
        logger.error(f"Fehler beim App-Stop: {e}")

    try:
        await asyncio.shield(app.shutdown())
    except Exception as e:
        logger.error(f"Fehler beim App-Shutdown: {e}")

    # IMAP-Task sauber beenden
    if not imap_task.done():
        try:
            await asyncio.wait_for(asyncio.shield(imap_task), timeout=10)
        except asyncio.TimeoutError:
            logger.warning("IMAP-Task hat Shutdown-Timeout - cancel")
            imap_task.cancel()
            try:
                await imap_task
            except (asyncio.CancelledError, Exception):
                pass
        except Exception as e:
            logger.error(f"Fehler beim IMAP-Task-Shutdown: {e}")

    # Bexio-Client aufraeumen
    try:
        await asyncio.shield(bexio_client.close())
    except Exception as e:
        logger.error(f"Fehler beim Bexio-Client-Shutdown: {e}")

    logger.info("👋 Bot beendet.")


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

    def _signal_handler(sig_name: str):
        logger.info(f"Signal {sig_name} empfangen – leite Shutdown ein")
        stop_event.set()

    loop = asyncio.get_running_loop()
    # SIGTERM kommt von Railway bei Deploys
    # SIGINT kommt bei Ctrl+C lokal
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler, sig.name)
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
    except asyncio.CancelledError:
        # asyncio.run() hat den Task gecancelt (z.B. durch KeyboardInterrupt
        # bevor der Signal-Handler greifen konnte) – trotzdem sauber beenden.
        logger.info("Task gecancelt – starte Shutdown")
    finally:
        await _shutdown(app, imap_task)


def main() -> None:
    """Sync-Wrapper fuer asyncio.run() - Entry-Point von Python."""
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        # asyncio.run() propagiert KeyboardInterrupt nach dem Task-Cancel.
        # _shutdown() wurde bereits im finally-Block von _main() ausgefuehrt.
        logger.info("Prozess durch KeyboardInterrupt beendet")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Fataler Fehler: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
