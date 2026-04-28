"""
IMAP-Inbox-Scan fuer Hostpoint (oder beliebige IMAP-Server).

Pollt das Postfach in einem festen Intervall, filtert nach
  - Anhang-Existenz (PDF / JPG / PNG / HEIC)
  - Keyword-Match in Subject ODER Body (case-insensitive Regex)
und reicht passende Mails an die bestehende Invoice-Pipeline weiter.

Idempotenz via Supabase-Tabelle 'processed_emails'. Wir setzen kein
\\Seen-Flag - User kann die Mailbox normal in Outlook lesen.
"""
import asyncio
import re
from typing import Iterable, List, Optional, Tuple

from imap_tools import MailBox, AND, MailMessage, MailAttachment

from app.config import settings
from app.utils import setup_logger, truncate
from app import db, bot as bot_module


logger = setup_logger(__name__)


SUPPORTED_MIME_PREFIXES = ("application/pdf", "image/")
SUPPORTED_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".heic", ".heif")

# Outlook benennt eingebettete Inline-Bilder (Signaturen, HTML-Banner) als
# image001.jpg, image002.png etc. Echte Foto-Anhaenge heissen anders.
INLINE_IMAGE_NAME_RE = re.compile(r"^image\d{3,4}\.(jpe?g|png|gif|bmp)$", re.IGNORECASE)
# Echte Beleg-Fotos sind quasi nie unter 20 KB.
INLINE_IMAGE_MIN_SIZE_BYTES = 20 * 1024


def _is_likely_inline_image(att: MailAttachment) -> bool:
    """
    Heuristik fuer Outlook-Inline-Bilder (Signaturen, eingebettete Banner):
    Wenn mind. 2 der 3 Signale stimmen, behandeln wir das Bild als Inline.
    PDFs werden hier nie gefiltert.
    """
    mime = (att.content_type or "").lower()
    if not mime.startswith("image/"):
        return False

    has_cid = bool(getattr(att, "content_id", None))
    name = (att.filename or "").strip().lower()
    name_matches = bool(INLINE_IMAGE_NAME_RE.match(name))
    size = len(att.payload) if att.payload else 0
    is_tiny = 0 < size < INLINE_IMAGE_MIN_SIZE_BYTES

    return sum([has_cid, name_matches, is_tiny]) >= 2


def _attachment_is_supported(att: MailAttachment) -> bool:
    """PDF / JPG / PNG / HEIC zaehlen. Sonstiges ignorieren."""
    mime = (att.content_type or "").lower()
    if any(mime.startswith(p) for p in SUPPORTED_MIME_PREFIXES):
        return True
    name = (att.filename or "").lower()
    return name.endswith(SUPPORTED_EXTENSIONS)


def _supported_attachments(msg: MailMessage) -> List[MailAttachment]:
    result: List[MailAttachment] = []
    for a in msg.attachments:
        if not _attachment_is_supported(a):
            continue
        if _is_likely_inline_image(a):
            logger.debug(
                f"Inline-Bild ignoriert: name={a.filename!r} "
                f"size={len(a.payload) if a.payload else 0} "
                f"cid={getattr(a, 'content_id', None)!r}"
            )
            continue
        result.append(a)
    return result


def _matches_keywords(msg: MailMessage, pattern: re.Pattern) -> bool:
    """Subject ODER Body matcht."""
    subject = msg.subject or ""
    if pattern.search(subject):
        return True
    body = (msg.text or "") + " " + (msg.html or "")
    return bool(pattern.search(body))


def _normalize_mime(att: MailAttachment) -> str:
    """Bexio/Gemini-Pipeline erwartet bekannte MIME-Types."""
    mime = (att.content_type or "").lower().strip()
    if mime in ("application/pdf", "image/jpeg", "image/png", "image/heic", "image/heif"):
        return mime
    name = (att.filename or "").lower()
    if name.endswith(".pdf"):
        return "application/pdf"
    if name.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if name.endswith(".png"):
        return "image/png"
    if name.endswith((".heic", ".heif")):
        return "image/heic"
    return "application/octet-stream"


async def _process_message(
    bot,
    msg: MailMessage,
    pattern: re.Pattern,
    account: str,
    folder: str,
    notify_chat_id: int,
) -> None:
    """Verarbeitet eine einzelne Mail. Markiert UID als processed/filtered/failed."""
    uid = msg.uid
    if not uid:
        logger.warning("Mail ohne UID uebersprungen")
        return

    if db.is_email_uid_processed(uid, folder=folder, account=account):
        return

    subject = (msg.subject or "")[:500]
    from_addr = (msg.from_ or "")[:200]

    attachments = _supported_attachments(msg)
    if not attachments:
        db.mark_email_uid_processed(
            uid=uid, folder=folder, account=account,
            status="no_attachment", subject=subject, from_address=from_addr,
        )
        return

    if not _matches_keywords(msg, pattern):
        db.mark_email_uid_processed(
            uid=uid, folder=folder, account=account,
            status="filtered", subject=subject, from_address=from_addr,
        )
        return

    logger.info(
        f"IMAP-Treffer uid={uid} from={truncate(from_addr, 60)} "
        f"subject='{truncate(subject, 60)}' attachments={len(attachments)}"
    )

    last_invoice_id: Optional[str] = None
    error_message: Optional[str] = None

    for idx, att in enumerate(attachments):
        try:
            mime = _normalize_mime(att)
            filename = att.filename or f"mail_{uid}_{idx}.bin"
            invoice_id = await bot_module.process_invoice_bytes(
                bot=bot,
                notify_chat_id=notify_chat_id,
                file_bytes=att.payload,
                filename=filename,
                mime_type=mime,
                file_size=len(att.payload) if att.payload else None,
                source="imap",
                source_reference=f"{account}/{folder}/{uid}",
                actor=f"imap:{account}",
            )
            if invoice_id:
                last_invoice_id = invoice_id
        except Exception as e:
            logger.exception(f"Fehler beim Verarbeiten Attachment {att.filename} aus uid={uid}: {e}")
            error_message = str(e)[:500]

    db.mark_email_uid_processed(
        uid=uid,
        folder=folder,
        account=account,
        status="failed" if error_message and not last_invoice_id else "processed",
        invoice_id=last_invoice_id,
        subject=subject,
        from_address=from_addr,
        error=error_message,
    )


def _fetch_candidate_uids(host: str, port: int, user: str, password: str, folder: str) -> List[str]:
    """
    Verbindet sync (imap-tools), holt UIDs der letzten Mails im Ordner.
    Limitiert auf die letzten 200, damit der erste Run nicht das ganze
    Postfach scannt.
    """
    with MailBox(host, port=port).login(user, password, initial_folder=folder) as mb:
        uids = mb.uids(AND(all=True))
    # Neueste zuerst, max 200
    return list(reversed(uids))[:200]


def _fetch_message(
    host: str, port: int, user: str, password: str, folder: str, uid: str
) -> Optional[MailMessage]:
    """Holt eine einzelne Mail per UID. None wenn nicht (mehr) vorhanden."""
    with MailBox(host, port=port).login(user, password, initial_folder=folder) as mb:
        for msg in mb.fetch(AND(uid=uid), mark_seen=False, bulk=False):
            return msg
    return None


async def run_imap_poller(
    application,
    stop_event: asyncio.Event,
) -> None:
    """
    Haupt-Loop. Wird parallel zum Telegram-Polling gestartet.

    Verbindet pro Iteration neu, statt eine Long-Lived-IMAP-Connection zu
    halten - robuster gegen Netzwerk-Hickups, einfacher als IDLE.
    """
    if not settings.imap_enabled:
        logger.info("IMAP-Poller deaktiviert (IMAP_ENABLED=false)")
        return

    if not settings.imap_user or not settings.imap_password:
        logger.error("IMAP_ENABLED=true aber IMAP_USER/PASSWORD fehlen - Poller stoppt")
        return

    notify_chat_id = settings.imap_notify_chat_id
    if not notify_chat_id:
        logger.error(
            "Keine notify_chat_id ermittelbar - IMAP-Poller stoppt. "
            "Setze TELEGRAM_NOTIFY_CHAT_ID oder TELEGRAM_ALLOWED_CHAT_IDS."
        )
        return

    try:
        pattern = re.compile(settings.imap_keywords_regex, re.IGNORECASE)
    except re.error as e:
        logger.error(f"IMAP_KEYWORDS_REGEX ungueltig: {e} - Poller stoppt")
        return

    host = settings.imap_host
    port = settings.imap_port
    user = settings.imap_user
    password = settings.imap_password
    folder = settings.imap_folder
    interval = max(20, settings.imap_poll_interval_seconds)

    logger.info(
        f"IMAP-Poller startet: {user}@{host}:{port} folder={folder} "
        f"interval={interval}s notify_chat={notify_chat_id}"
    )

    bot = application.bot

    while not stop_event.is_set():
        try:
            uids = await asyncio.to_thread(
                _fetch_candidate_uids, host, port, user, password, folder
            )
            for uid in uids:
                if stop_event.is_set():
                    break
                if db.is_email_uid_processed(uid, folder=folder, account=user):
                    continue
                try:
                    msg = await asyncio.to_thread(
                        _fetch_message, host, port, user, password, folder, uid
                    )
                except Exception as e:
                    logger.warning(f"IMAP-Fetch uid={uid} fehlgeschlagen: {e}")
                    continue
                if msg is None:
                    continue
                try:
                    await _process_message(
                        bot=bot,
                        msg=msg,
                        pattern=pattern,
                        account=user,
                        folder=folder,
                        notify_chat_id=notify_chat_id,
                    )
                except Exception as e:
                    logger.exception(f"Fehler bei _process_message uid={uid}: {e}")

        except Exception as e:
            logger.exception(f"IMAP-Poll-Iteration fehlgeschlagen: {e}")

        # Warten bis naechste Iteration oder Shutdown
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass

    logger.info("IMAP-Poller gestoppt")
