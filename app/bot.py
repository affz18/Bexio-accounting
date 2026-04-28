"""
Telegram Bot - Hauptlogik.

Workflow:
1. User sendet PDF/Bild
2. Bot speichert Datei in Supabase Storage
3. Bot ruft Gemini auf -> strukturierte Daten
4. Bot matcht Vendor (Memory oder neu)
5. Bot zeigt Vorschlag mit Buttons: [Buchen] [Anderes Konto] [Verwerfen]
6. Bei Buchen -> Bexio API
7. Bei Anderes Konto -> Konto-Auswahl als Buttons
8. Lernen: Vendor-Mapping wird aktualisiert
"""
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Document,
    PhotoSize,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from app.config import settings
from app.utils import setup_logger, format_chf, truncate, normalize_vendor_name
from app.models import InvoiceExtractionResult
from app import db, storage, bexio as bexio_module, gemini
from app.learn import learn_from_bexio_history, ProgressThrottle


logger = setup_logger(__name__)


# =========================================================
# AUTH MIDDLEWARE
# =========================================================

async def _check_auth(update: Update) -> bool:
    """
    Prueft ob User berechtigt ist. Sendet Ablehnung wenn nicht.
    
    Check 1: ENV-Whitelist (Bootstrap, damit Bot auch ohne DB-Eintrag startbar ist)
    Check 2: Supabase authorized_users Tabelle
    """
    if not update.effective_chat:
        return False
    
    chat_id = update.effective_chat.id
    
    # Check 1: ENV-Whitelist
    env_allowed = settings.allowed_chat_ids_list
    if env_allowed and chat_id in env_allowed:
        return True
    
    # Check 2: DB
    if db.is_user_authorized(chat_id):
        return True
    
    # Nicht authorized
    logger.warning(f"Nicht-autorisierter Zugriff von Chat-ID {chat_id}")
    await update.effective_message.reply_text(
        "🚫 Dieser Bot ist nicht fuer dich freigegeben.\n\n"
        f"Deine Chat-ID: `{chat_id}`\n\n"
        "Kontaktiere den Admin, falls du Zugriff brauchst.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return False


# =========================================================
# COMMANDS
# =========================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Begruessung."""
    if not await _check_auth(update):
        return
    
    await update.message.reply_text(
        "👋 *VisioSkin Accounting Agent*\n\n"
        "Schick mir eine Rechnung als PDF/Foto - ich verbuche sie in Bexio.\n"
        "Schick mir eine camt.054-Datei vom Online-Banking - ich gleiche "
        "Zahlungen automatisch ab.\n\n"
        "*Befehle:*\n"
        "/sync — Bexio-Kontenplan aktualisieren\n"
        "/learn — Aus bestehender Bexio-History lernen\n"
        "/review — Match-Vorschlaege fuer Bank-Zahlungen durchgehen\n"
        "/stats — Statistik anzeigen\n"
        "/vendors — Gelernte Lieferanten\n"
        "/help — Hilfe\n\n"
        "_Tipp: Beim ersten Start `/sync` und dann `/learn` ausfuehren._",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hilfe."""
    if not await _check_auth(update):
        return
    
    await update.message.reply_text(
        "*So funktioniert der Bot*\n\n"
        "1️⃣ Schick eine Rechnung als PDF oder Foto\n"
        "2️⃣ Ich extrahiere die Daten automatisch\n"
        "3️⃣ Ich schlage dir ein Konto vor\n"
        "4️⃣ Du bestaetigst mit einem Klick\n"
        "5️⃣ Ich buche in Bexio\n\n"
        "*Unterstuetzte Formate:* PDF, JPG, PNG, HEIC (max 10 MB)\n\n"
        "*Was ich lerne:*\n"
        "Jedes Mal wenn du einen Lieferanten bestaetigst, merke ich mir "
        "welches Konto du nutzt. Beim naechsten Mal schlage ich es automatisch vor.\n\n"
        "*Schon mal in Bexio gebucht?* Mit `/learn` lese ich die letzten 12 "
        "Monate Bexio-Rechnungen und uebernehme dein bisheriges Buchungsmuster.\n\n"
        "*Bei Problemen:* Schick `/stats` um zu sehen ob Belege haengen geblieben sind.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Synchronisiert Kontenplan und MwSt-Codes aus Bexio."""
    if not await _check_auth(update):
        return
    
    msg = await update.message.reply_text("⏳ Synchronisiere mit Bexio…")
    
    try:
        # Accounts holen
        accounts = await bexio_module.bexio.list_accounts()
        account_count = db.sync_accounts(accounts)
        
        # Taxes holen
        taxes = await bexio_module.bexio.list_taxes()
        tax_count = db.sync_taxes(taxes)
        
        await msg.edit_text(
            f"✅ *Synchronisation erfolgreich*\n\n"
            f"📊 Konten: {account_count}\n"
            f"🏷 MwSt-Codes: {tax_count}\n\n"
            f"Du kannst jetzt Rechnungen senden.",
            parse_mode=ParseMode.MARKDOWN,
        )
        db.log_action(None, "sync", actor=f"telegram:{update.effective_chat.id}", details={
            "accounts": account_count,
            "taxes": tax_count,
        })
    except bexio_module.BexioError as e:
        logger.error(f"Sync fehlgeschlagen: {e}")
        await msg.edit_text(
            f"❌ *Fehler beim Sync*\n\n"
            f"`{truncate(str(e), 200)}`\n\n"
            f"Pruefe deinen Bexio API Token.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def cmd_learn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lernt Vendor->Konto-Mapping aus bestehender Bexio-History."""
    if not await _check_auth(update):
        return

    msg = await update.message.reply_text(
        "🧠 *Lern-Vorgang gestartet*\n\n"
        "Ich lese deine letzten 12 Monate Bexio-Rechnungen und baue daraus "
        "das Lieferanten-Memory auf.\n\n"
        "_Das kann je nach Anzahl Belege ein paar Minuten dauern._",
        parse_mode=ParseMode.MARKDOWN,
    )

    async def _edit(text: str) -> None:
        await msg.edit_text(f"🧠 {text}")

    progress = ProgressThrottle(_edit, min_interval_s=2.0)

    try:
        stats = await learn_from_bexio_history(
            months_back=12,
            max_bills=1000,
            progress=progress,
        )
        await msg.edit_text(
            f"✅ *Lern-Vorgang abgeschlossen*\n\n"
            f"📋 Bills geladen: {stats.bills_listed}\n"
            f"⚙️ Verarbeitet: {stats.bills_processed}\n"
            f"⏭ Uebersprungen: {stats.bills_skipped}\n\n"
            f"🆕 Neue Lieferanten: {stats.vendors_created}\n"
            f"🔄 Aktualisierte: {stats.vendors_updated}\n"
            f"➖ Unveraendert: {stats.vendors_skipped}\n\n"
            f"_Mit /vendors siehst du was gelernt wurde._",
            parse_mode=ParseMode.MARKDOWN,
        )
        db.log_action(None, "learn", actor=f"telegram:{update.effective_chat.id}", details={
            "bills_processed": stats.bills_processed,
            "vendors_created": stats.vendors_created,
            "vendors_updated": stats.vendors_updated,
        })
    except RuntimeError as e:
        # z.B. wenn /sync fehlt
        await msg.edit_text(
            f"⚠️ *Lernen nicht moeglich*\n\n{truncate(str(e), 200)}",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.exception(f"Lern-Fehler: {e}")
        await msg.edit_text(
            f"❌ *Fehler beim Lernen*\n\n`{truncate(str(e), 300)}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Zeigt Statistik."""
    if not await _check_auth(update):
        return
    
    stats = db.get_stats()
    
    await update.message.reply_text(
        f"📊 *Statistik*\n\n"
        f"Gesamt: {stats['total']}\n"
        f"✅ Gebucht: {stats['booked']}\n"
        f"⏳ Pending: {stats['pending']}\n"
        f"❌ Fehlgeschlagen: {stats['failed']}\n"
        f"🗑 Verworfen: {stats['rejected']}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_vendors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Listet gelernte Lieferanten."""
    if not await _check_auth(update):
        return
    
    vendors = db.list_vendors(limit=30)
    
    if not vendors:
        await update.message.reply_text(
            "📂 Noch keine Lieferanten gelernt.\n\n"
            "Sobald du die ersten Rechnungen buchst, erscheinen sie hier."
        )
        return
    
    lines = ["📂 *Gelernte Lieferanten*\n"]
    for v in vendors:
        conf_icon = "🟢" if v.confidence_score >= 0.8 else "🟡" if v.confidence_score >= 0.5 else "⚪"
        account_info = f"→ {v.default_account_nr}" if v.default_account_nr else "(noch kein Konto)"
        lines.append(
            f"{conf_icon} *{truncate(v.name, 30)}* {account_info} ({v.booking_count}x)"
        )
    
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


# =========================================================
# DATEI-EMPFANG (Haupt-Workflow)
# =========================================================

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """PDF, Bild oder camt-Bank-Datei als Document empfangen."""
    if not await _check_auth(update):
        return

    doc: Document = update.message.document

    # Validierung
    if doc.file_size and doc.file_size > 10 * 1024 * 1024:
        await update.message.reply_text("❌ Datei zu gross (max 10 MB).")
        return

    mime = (doc.mime_type or "application/octet-stream").lower()
    filename = doc.file_name or "document.bin"
    fname_lower = filename.lower()

    # camt.054 / camt.053: Schweizer Bank-Bewegungs-Datei (XML)
    is_camt = (
        fname_lower.endswith((".xml", ".054", ".053"))
        or "camt" in fname_lower
        or mime in ("text/xml", "application/xml")
    )

    if is_camt:
        await _process_camt_file(
            update=update,
            context=context,
            file_id=doc.file_id,
            filename=filename,
        )
        return

    supported = ("application/pdf", "image/jpeg", "image/png", "image/jpg", "image/heic", "image/heif")
    if mime not in supported:
        await update.message.reply_text(
            f"❌ Dateityp `{mime}` nicht unterstuetzt.\n"
            "Schick PDF, JPG, PNG, HEIC oder camt.054/.053 (XML).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await _process_invoice_file(
        update=update,
        context=context,
        file_id=doc.file_id,
        filename=filename,
        mime_type=mime,
        file_size=doc.file_size,
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Bild als Photo empfangen (Telegram komprimiert automatisch)."""
    if not await _check_auth(update):
        return
    
    # Groesste Version nehmen
    photo: PhotoSize = update.message.photo[-1]
    
    await _process_invoice_file(
        update=update,
        context=context,
        file_id=photo.file_id,
        filename=f"photo_{photo.file_unique_id}.jpg",
        mime_type="image/jpeg",
        file_size=photo.file_size,
    )


async def _process_invoice_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    file_id: str,
    filename: str,
    mime_type: str,
    file_size: Optional[int],
) -> None:
    """Telegram-Pfad: Datei aus Telegram holen, dann gemeinsamen Kern aufrufen."""
    chat_id = update.effective_chat.id

    status_msg = await update.message.reply_text(
        f"📄 Beleg empfangen ({truncate(filename, 40)})\n"
        f"⏳ Lade herunter und analysiere…"
    )

    try:
        tg_file = await context.bot.get_file(file_id)
        file_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        logger.exception(f"Telegram-Download fehlgeschlagen: {e}")
        await status_msg.edit_text(f"❌ Download-Fehler: `{truncate(str(e), 150)}`",
                                   parse_mode=ParseMode.MARKDOWN)
        return

    await process_invoice_bytes(
        bot=context.bot,
        notify_chat_id=chat_id,
        file_bytes=file_bytes,
        filename=filename,
        mime_type=mime_type,
        file_size=file_size,
        source="telegram",
        source_reference=str(update.message.message_id),
        actor=f"telegram:{chat_id}",
        status_msg=status_msg,
    )


async def process_invoice_bytes(
    *,
    bot,
    notify_chat_id: int,
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    file_size: Optional[int],
    source: str,
    source_reference: Optional[str],
    actor: str,
    status_msg=None,
) -> Optional[str]:
    """
    Source-agnostischer Pipeline-Kern.

    Wird sowohl von Telegram-Handlers als auch vom IMAP-Connector aufgerufen.
    Wenn status_msg gegeben ist, wird die existierende Nachricht editiert
    (Telegram-Pfad). Sonst wird eine neue Nachricht in notify_chat_id gepostet
    (IMAP-Pfad).

    Returns: invoice_id bei Erfolg (oder bei "not_invoice"), sonst None.
    """

    async def _say(text: str, **kwargs):
        """Schickt Status entweder als Edit oder als neue Message."""
        if status_msg is not None:
            await status_msg.edit_text(text, **kwargs)
            return status_msg
        return await bot.send_message(chat_id=notify_chat_id, text=text, **kwargs)

    current_msg = status_msg

    try:
        storage_path = storage.upload_invoice_file(
            file_bytes=file_bytes,
            original_filename=filename,
            mime_type=mime_type,
        )
        if not storage_path:
            await _say("❌ Fehler beim Speichern der Datei.")
            return None

        invoice_id = db.create_pending_invoice(
            source=source,
            source_reference=source_reference,
            file_path=storage_path,
            original_filename=filename,
            file_size_bytes=file_size,
            file_mime_type=mime_type,
        )
        if not invoice_id:
            await _say("❌ Fehler beim DB-Eintrag.")
            return None

        db.log_action(invoice_id, "received", actor=actor, details={
            "filename": filename,
            "mime_type": mime_type,
            "size": file_size,
            "source": source,
        })

        current_msg = await _say(
            f"📄 Beleg empfangen ({truncate(filename, 40)})\n"
            f"🧠 Gemini analysiert das Dokument…"
        )

        try:
            result = await gemini.extract_invoice(file_bytes, mime_type)
        except gemini.GeminiOverloadedError as e:
            db.mark_invoice_failed(invoice_id, f"Gemini ueberlastet: {e}")
            db.log_action(invoice_id, "extraction_failed",
                          details={"error": str(e), "reason": "overloaded"})
            if current_msg:
                await current_msg.edit_text(
                    "⏳ *Gemini ist gerade ueberlastet*\n\n"
                    "Die Google-Server haben hohe Auslastung. "
                    "Bitte spaeter erneut versuchen.",
                    parse_mode=ParseMode.MARKDOWN,
                )
            return None
        except gemini.GeminiError as e:
            db.mark_invoice_failed(invoice_id, f"Gemini-Fehler: {e}")
            db.log_action(invoice_id, "extraction_failed", details={"error": str(e)})
            if current_msg:
                await current_msg.edit_text(
                    f"❌ *Extraktion fehlgeschlagen*\n\n`{truncate(str(e), 200)}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
            return None

        if not result.is_invoice:
            db.update_invoice_extraction(
                invoice_id=invoice_id,
                extracted_data=result.model_dump(),
                status="not_invoice",
            )
            db.log_action(invoice_id, "not_invoice")
            if current_msg:
                await current_msg.edit_text(
                    "🤔 Das sieht nicht nach einer Rechnung aus.\n"
                    "Ich ignoriere das Dokument."
                )
            return invoice_id

        db.update_invoice_extraction(
            invoice_id=invoice_id,
            extracted_data=result.model_dump(),
            vendor_name=result.vendor_name,
            invoice_number=result.invoice_number,
            invoice_date=result.invoice_date,
            due_date=result.due_date,
            total_amount=result.total_amount,
            vat_amount=result.vat_amount,
            currency=result.currency,
            iban=result.iban,
            reference_number=result.reference_number,
            status="extracted",
        )
        db.log_action(invoice_id, "extracted", details=result.model_dump())

        await _show_suggestion(
            status_msg=current_msg,
            invoice_id=invoice_id,
            result=result,
        )
        return invoice_id

    except Exception as e:
        logger.exception(f"Unerwarteter Fehler beim Datei-Processing: {e}")
        try:
            if current_msg:
                await current_msg.edit_text(
                    f"❌ *Unerwarteter Fehler*\n\n`{truncate(str(e), 200)}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await bot.send_message(
                    chat_id=notify_chat_id,
                    text=f"❌ *Unerwarteter Fehler*\n\n`{truncate(str(e), 200)}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
        except Exception:
            pass
        return None


# =========================================================
# VORSCHLAG ANZEIGEN
# =========================================================

async def _show_suggestion(
    status_msg,
    invoice_id: str,
    result: InvoiceExtractionResult,
) -> None:
    """Baut und zeigt die Freigabe-Nachricht mit Buttons."""
    
    # Vendor-Memory pruefen
    vendor = None
    if result.vendor_name:
        vendor = db.find_vendor_by_name(result.vendor_name)
    if not vendor and result.iban:
        vendor = db.find_vendor_by_iban(result.iban)
    
    account_nr: Optional[str] = None
    account_name: Optional[str] = None
    account_bexio_id: Optional[int] = None
    tax_id: Optional[int] = None
    tax_rate: Optional[float] = None
    confidence = 0.0
    is_known = False
    
    if vendor and vendor.default_account_id:
        account_bexio_id = vendor.default_account_id
        account_nr = vendor.default_account_nr
        tax_id = vendor.default_tax_id
        tax_rate = vendor.default_tax_rate
        confidence = vendor.confidence_score
        is_known = True
        
        # Account-Namen aus Cache holen
        all_accounts = db.get_all_accounts()
        for a in all_accounts:
            if a["bexio_account_id"] == account_bexio_id:
                account_name = a["account_name"]
                break
    else:
        # Unbekannter Vendor -> Gemini fragen
        expense_accounts = db.get_expense_accounts()
        if expense_accounts and result.vendor_name and result.total_amount:
            acc_id, conf, reasoning = await gemini.suggest_account(
                vendor_name=result.vendor_name,
                total_amount=result.total_amount,
                available_accounts=expense_accounts,
            )
            if acc_id:
                account_bexio_id = acc_id
                confidence = conf
                for a in expense_accounts:
                    if a["bexio_account_id"] == acc_id:
                        account_nr = a["account_nr"]
                        account_name = a["account_name"]
                        break
        
        # MwSt-Code erraten aus rate
        if result.vat_rate is not None:
            tax = db.find_tax_by_rate(result.vat_rate)
            if tax:
                tax_id = tax["bexio_tax_id"]
                tax_rate = tax["tax_rate"]
    
    # Fallback wenn gar kein Konto ermittelt
    if not account_bexio_id:
        expense_accounts = db.get_expense_accounts()
        if expense_accounts:
            account_bexio_id = expense_accounts[0]["bexio_account_id"]
            account_nr = expense_accounts[0]["account_nr"]
            account_name = expense_accounts[0]["account_name"]
            confidence = 0.1
    
    # Suggestion speichern
    db.update_invoice_suggestion(
        invoice_id=invoice_id,
        suggested_vendor_id=vendor.id if vendor else None,
        suggested_account_id=account_bexio_id,
        suggested_tax_id=tax_id,
        confidence_score=confidence,
        status="awaiting_approval",
    )
    
    # Nachricht bauen
    confidence_icon = "🟢" if confidence >= 0.8 else "🟡" if confidence >= 0.5 else "⚪"
    known_badge = "💾 Bekannt" if is_known else "🆕 Neu"
    
    msg_text = (
        f"📄 *Rechnung erkannt*\n\n"
        f"🏢 *Lieferant:* {result.vendor_name or '?'} ({known_badge})\n"
        f"💰 *Betrag:* {format_chf(result.total_amount)}\n"
        f"📅 *Datum:* {result.invoice_date or '?'}\n"
    )
    if result.invoice_number:
        msg_text += f"🔢 *Nr:* `{truncate(result.invoice_number, 30)}`\n"
    if result.vat_rate is not None:
        msg_text += f"🏷 *MwSt:* {result.vat_rate}% ({format_chf(result.vat_amount)})\n"
    
    msg_text += (
        f"\n💡 *Vorschlag:* {account_nr or '?'} – {account_name or '?'}\n"
        f"{confidence_icon} Konfidenz: {int(confidence * 100)}%"
    )
    
    # Buttons
    keyboard = [
        [
            InlineKeyboardButton("✅ Buchen", callback_data=f"book:{invoice_id}"),
            InlineKeyboardButton("📝 Anderes Konto", callback_data=f"change:{invoice_id}"),
        ],
        [
            InlineKeyboardButton("❌ Verwerfen", callback_data=f"reject:{invoice_id}"),
        ],
    ]
    
    await status_msg.edit_text(
        msg_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )


# =========================================================
# CALLBACK-HANDLERS (Button-Klicks)
# =========================================================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispatcher fuer alle Inline-Button-Klicks."""
    if not await _check_auth(update):
        return
    
    query = update.callback_query
    await query.answer()  # Sofort ack, sonst haengt der Button-Spinner
    
    data = query.data or ""
    
    if data.startswith("matchbook:"):
        match_id = data.split(":", 1)[1]
        await _callback_match_book(query, match_id)
    elif data.startswith("matchskip:"):
        match_id = data.split(":", 1)[1]
        await _callback_match_skip(query, match_id)
    elif data.startswith("book:"):
        invoice_id = data.split(":", 1)[1]
        await _callback_book(query, invoice_id)
    elif data.startswith("change:"):
        invoice_id = data.split(":", 1)[1]
        await _callback_change_account(query, invoice_id)
    elif data.startswith("setacc:"):
        # Format: setacc:invoice_id:account_bexio_id
        parts = data.split(":")
        if len(parts) == 3:
            await _callback_set_account(query, parts[1], int(parts[2]))
    elif data.startswith("reject:"):
        invoice_id = data.split(":", 1)[1]
        await _callback_reject(query, invoice_id)
    elif data.startswith("cancel:"):
        invoice_id = data.split(":", 1)[1]
        # Zurueck zum Haupt-Vorschlag
        inv = db.get_invoice(invoice_id)
        if inv and inv.get("extracted_data"):
            result = InvoiceExtractionResult(**inv["extracted_data"])
            await _show_suggestion_from_callback(query, invoice_id, result)


async def _callback_book(query, invoice_id: str) -> None:
    """User klickt auf Buchen."""
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        await query.edit_message_text("❌ Beleg nicht gefunden.")
        return
    
    if invoice["status"] == "booked":
        await query.edit_message_text("ℹ️ Schon gebucht.")
        return
    
    await query.edit_message_text("⏳ Buche in Bexio…")
    
    try:
        bill_result = await _create_bexio_bill(invoice)
        if not bill_result:
            await query.edit_message_text("❌ Buchung fehlgeschlagen (siehe Logs).")
            return
        
        bill_id = bill_result.get("id")
        db.mark_invoice_booked(invoice_id, bill_id)
        db.log_action(invoice_id, "booked", actor=f"telegram:{query.from_user.id}", details={
            "bexio_bill_id": bill_id,
        })
        
        # Vendor-Memory aktualisieren (lernen!)
        await _update_vendor_memory(invoice)
        
        await query.edit_message_text(
            f"✅ *Gebucht in Bexio*\n\n"
            f"Bill #{bill_id}\n"
            f"{invoice.get('vendor_name') or '?'}\n"
            f"{format_chf(invoice.get('total_amount'))}",
            parse_mode=ParseMode.MARKDOWN,
        )
    except bexio_module.BexioError as e:
        db.mark_invoice_failed(invoice_id, str(e))
        db.log_action(invoice_id, "booking_failed", details={"error": str(e)})
        await query.edit_message_text(
            f"❌ *Bexio-Fehler*\n\n`{truncate(str(e), 300)}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def _callback_change_account(query, invoice_id: str) -> None:
    """User will anderes Konto waehlen."""
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        await query.edit_message_text("❌ Beleg nicht gefunden.")
        return
    
    accounts = db.get_expense_accounts()
    if not accounts:
        await query.edit_message_text(
            "❌ Keine Konten im Cache. Fuehre erst `/sync` aus.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    
    # Zeige Top-20 Konten als Buttons (2 pro Reihe)
    buttons = []
    shown = accounts[:20]
    for i in range(0, len(shown), 2):
        row = []
        for acc in shown[i:i+2]:
            label = f"{acc['account_nr']} {truncate(acc['account_name'], 18)}"
            row.append(InlineKeyboardButton(
                label,
                callback_data=f"setacc:{invoice_id}:{acc['bexio_account_id']}",
            ))
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton("◀️ Zurueck", callback_data=f"cancel:{invoice_id}")])
    
    vendor_name = invoice.get("vendor_name") or "?"
    await query.edit_message_text(
        f"*Waehle ein Konto*\n"
        f"fuer _{truncate(vendor_name, 40)}_\n\n"
        f"(Zeige {len(shown)} von {len(accounts)} Konten)",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN,
    )


async def _callback_set_account(query, invoice_id: str, account_bexio_id: int) -> None:
    """User hat manuell ein Konto gewaehlt -> buchen."""
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        await query.edit_message_text("❌ Beleg nicht gefunden.")
        return
    
    # Update suggested account
    db.update_invoice_suggestion(
        invoice_id=invoice_id,
        suggested_account_id=account_bexio_id,
        confidence_score=1.0,  # User hat bestaetigt -> volle Konfidenz
        status="awaiting_approval",
    )
    
    # Aktualisiertes Invoice-Objekt holen
    invoice = db.get_invoice(invoice_id)
    
    await query.edit_message_text("⏳ Buche in Bexio…")
    
    try:
        bill_result = await _create_bexio_bill(invoice)
        if not bill_result:
            await query.edit_message_text("❌ Buchung fehlgeschlagen.")
            return
        
        bill_id = bill_result.get("id")
        db.mark_invoice_booked(invoice_id, bill_id)
        db.log_action(invoice_id, "booked", actor=f"telegram:{query.from_user.id}", details={
            "bexio_bill_id": bill_id,
            "manual_account": account_bexio_id,
        })
        
        await _update_vendor_memory(invoice)
        
        await query.edit_message_text(
            f"✅ *Gebucht in Bexio*\n\n"
            f"Bill #{bill_id}\n"
            f"{invoice.get('vendor_name') or '?'}\n"
            f"{format_chf(invoice.get('total_amount'))}\n\n"
            f"_Konto-Mapping gespeichert fuer naechstes Mal._",
            parse_mode=ParseMode.MARKDOWN,
        )
    except bexio_module.BexioError as e:
        db.mark_invoice_failed(invoice_id, str(e))
        await query.edit_message_text(
            f"❌ *Bexio-Fehler*\n\n`{truncate(str(e), 300)}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def _callback_reject(query, invoice_id: str) -> None:
    """User verwirft den Beleg."""
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        await query.edit_message_text("❌ Beleg nicht gefunden.")
        return
    
    db.update_invoice_extraction(invoice_id=invoice_id, extracted_data={}, status="rejected")
    db.log_action(invoice_id, "rejected", actor=f"telegram:{query.from_user.id}")
    
    await query.edit_message_text("🗑 Beleg verworfen.")


async def _show_suggestion_from_callback(query, invoice_id: str, result: InvoiceExtractionResult):
    """Alternative zu _show_suggestion wenn wir von Callback kommen."""
    # Kleine Trick: wir rufen die gleiche Funktion auf mit dem Callback-Message-Obj
    class _Wrapper:
        def __init__(self, q):
            self._q = q
        async def edit_text(self, *args, **kwargs):
            return await self._q.edit_message_text(*args, **kwargs)
    
    await _show_suggestion(_Wrapper(query), invoice_id, result)


# =========================================================
# BEXIO BUCHUNG (Helper)
# =========================================================

async def _create_bexio_bill(invoice: dict) -> Optional[dict]:
    """
    Erstellt eine Bexio Bill aus einem Pending-Invoice.
    Legt Vendor-Kontakt in Bexio an wenn noetig.
    """
    vendor_name = invoice.get("vendor_name")
    if not vendor_name:
        raise bexio_module.BexioError("Lieferantenname fehlt")
    
    total = invoice.get("total_amount")
    if total is None:
        raise bexio_module.BexioError("Betrag fehlt")
    
    account_id = invoice.get("suggested_account_id")
    if not account_id:
        raise bexio_module.BexioError("Kein Konto ausgewaehlt")
    
    # Vendor in Bexio: suchen oder neu anlegen
    bexio_contact_id: Optional[int] = None
    
    # Erst im Memory pruefen
    vendor_memory = db.find_vendor_by_name(vendor_name)
    if vendor_memory and vendor_memory.bexio_contact_id:
        bexio_contact_id = vendor_memory.bexio_contact_id
    
    # Wenn nicht im Memory: in Bexio suchen
    if not bexio_contact_id:
        contacts = await bexio_module.bexio.search_contacts(vendor_name)
        if contacts:
            bexio_contact_id = contacts[0]["id"]
    
    # Wenn immer noch nicht: neu anlegen
    if not bexio_contact_id:
        new_contact = await bexio_module.bexio.create_supplier_contact(
            name=vendor_name,
            uid_number=None,  # koennte aus extracted_data kommen
            iban=invoice.get("iban"),
        )
        if new_contact:
            bexio_contact_id = new_contact.get("id")
    
    if not bexio_contact_id:
        raise bexio_module.BexioError(f"Konnte Lieferant '{vendor_name}' nicht in Bexio anlegen")
    
    # Datumsfelder. Wenn das Belegdatum im geschlossenen Geschaeftsjahr liegt,
    # lehnt Bexio das Booking ab (kommt als 404 zurueck, nicht als 422).
    # Wir clampen daher: alles vor dem 1.1. des aktuellen Jahres -> heute.
    today = datetime.now(timezone.utc).date()
    start_of_year = today.replace(month=1, day=1).isoformat()
    extracted_date = invoice.get("invoice_date")
    extracted_due = invoice.get("due_date")

    if extracted_date and extracted_date < start_of_year:
        logger.info(
            f"Belegdatum {extracted_date} liegt im geschlossenen Geschaeftsjahr "
            f"- clamp auf heute ({today.isoformat()})"
        )
        bill_date = today.isoformat()
        due_date = (today + timedelta(days=30)).isoformat()
    else:
        bill_date = extracted_date or today.isoformat()
        if extracted_due and extracted_due >= bill_date:
            due_date = extracted_due
        else:
            due_date = (today + timedelta(days=30)).isoformat()

    # Bill erstellen
    bill = await bexio_module.bexio.create_supplier_bill(
        vendor_bexio_id=bexio_contact_id,
        vendor_name=vendor_name,
        vendor_reference=invoice.get("invoice_number") or "—",
        bill_date=bill_date,
        due_date=due_date,
        total_amount=float(total),
        account_id=int(account_id),
        tax_id=invoice.get("suggested_tax_id"),
        currency_code=invoice.get("currency") or "CHF",
        title=f"Rechnung {vendor_name}",
    )
    
    # Vendor-Memory: bexio_contact_id speichern falls neu
    if bill and vendor_memory and not vendor_memory.bexio_contact_id:
        # Update wird durch _update_vendor_memory erledigt
        pass
    
    return bill


async def _update_vendor_memory(invoice: dict) -> None:
    """
    Aktualisiert das Lieferanten-Memory nach erfolgreicher Buchung.
    Lernt: dieser Lieferant -> dieses Konto.
    """
    vendor_name = invoice.get("vendor_name")
    if not vendor_name:
        return
    
    account_id = invoice.get("suggested_account_id")
    if not account_id:
        return
    
    # Account-Nummer ermitteln aus Cache
    account_nr = None
    for a in db.get_all_accounts():
        if a["bexio_account_id"] == account_id:
            account_nr = a["account_nr"]
            break
    
    # Tax-Rate aus extracted_data
    tax_rate = None
    extracted = invoice.get("extracted_data") or {}
    if isinstance(extracted, dict):
        tax_rate = extracted.get("vat_rate")
    
    # Existiert Vendor bereits?
    vendor = db.find_vendor_by_name(vendor_name)
    if vendor:
        db.update_vendor_mapping(
            vendor_id=vendor.id,
            account_id=account_id,
            account_nr=account_nr or "",
            tax_id=invoice.get("suggested_tax_id"),
            tax_rate=tax_rate,
        )
    else:
        # Neu anlegen
        db.create_vendor(
            name=vendor_name,
            default_account_id=account_id,
            default_account_nr=account_nr,
            default_tax_id=invoice.get("suggested_tax_id"),
            default_tax_rate=tax_rate,
            iban=invoice.get("iban"),
        )


# =========================================================
# BANK-RECONCILIATION (Phase 4)
# =========================================================
#
# Workflow:
# 1. User schickt camt.054/.053 als Document -> handle_document erkennt
#    es ueber Filename/MIME und routet zu _process_camt_file
# 2. _process_camt_file parsed XML -> Liste BankTransaction, speichert in
#    DB (idempotent), matched gegen offene Pending-Invoices, speichert
#    Top-1-Vorschlaege als payment_matches.status='proposed'
# 3. User ruft /review (oder klickt direkt nach Upload) -> Bot zeigt
#    proposed Matches einen nach dem anderen mit [Buchen]/[Skip]-Buttons
# 4. Bei Buchen: bexio.register_bill_payment -> Status auf 'booked'
# 5. Bei Skip: Status auf 'rejected'
#
# Voraussetzung: pending_invoice muss bexio_bill_id haben (= bereits in
# Bexio gebucht). Sonst kann keine Payment registriert werden.

async def _process_camt_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    file_id: str,
    filename: str,
) -> None:
    """Lädt camt-Datei aus Telegram, parst, matcht, speichert Vorschlaege."""
    chat_id = update.effective_chat.id

    status_msg = await update.message.reply_text(
        f"🏦 Bank-Datei empfangen ({truncate(filename, 40)})\n"
        f"⏳ Lade herunter…"
    )

    try:
        tg_file = await context.bot.get_file(file_id)
        file_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        logger.exception(f"camt-Download fehlgeschlagen: {e}")
        await status_msg.edit_text(
            f"❌ Download-Fehler: `{truncate(str(e), 150)}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Lokale Imports damit Phase-4-Module nur geladen werden wenn gebraucht
    from app.camt import parse_camt, CamtParseError
    from app.reconcile import find_matches

    await status_msg.edit_text("🏦 Parse Bank-Bewegungen…")

    try:
        transactions = parse_camt(file_bytes)
    except CamtParseError as e:
        await status_msg.edit_text(
            f"❌ *camt-Datei nicht lesbar*\n\n`{truncate(str(e), 200)}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not transactions:
        await status_msg.edit_text(
            "⚠️ Keine Bank-Bewegungen in der Datei gefunden."
        )
        return

    outgoing = [tx for tx in transactions if tx.is_outgoing]
    open_invoices = db.get_open_invoices_for_matching()

    if not open_invoices:
        await status_msg.edit_text(
            f"📊 *{len(transactions)} Bewegungen geparst* "
            f"({len(outgoing)} ausgehend)\n\n"
            f"ℹ️ Keine offenen Rechnungen in der DB - nichts zu matchen.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await status_msg.edit_text(
        f"🏦 {len(transactions)} Bewegungen geparst, {len(outgoing)} ausgehend\n"
        f"⏳ Matche gegen {len(open_invoices)} offene Rechnungen…"
    )

    saved_count = 0
    proposed_count = 0
    duplicate_count = 0

    for tx in transactions:
        if not tx.transaction_id:
            continue

        tx_payload = {
            "tenant_id": "visioskin",
            "bank_account_iban": tx.bank_account_iban,
            "transaction_id": tx.transaction_id,
            "end_to_end_id": tx.end_to_end_id,
            "structured_reference": tx.structured_reference,
            "booking_date": tx.booking_date.isoformat(),
            "value_date": tx.value_date.isoformat() if tx.value_date else None,
            "amount": tx.amount,
            "currency": tx.currency,
            "direction": tx.direction,
            "counterparty_name": tx.counterparty_name,
            "counterparty_iban": tx.counterparty_iban,
            "remittance_unstructured": tx.remittance_unstructured,
        }
        bank_tx_id = db.upsert_bank_transaction(tx_payload)
        if not bank_tx_id:
            duplicate_count += 1
            continue
        saved_count += 1

        if not tx.is_outgoing:
            continue

        candidates = find_matches(tx, open_invoices)
        if not candidates:
            continue

        top = candidates[0]
        match_id = db.insert_payment_match({
            "tenant_id": "visioskin",
            "bank_transaction_id": bank_tx_id,
            "pending_invoice_id": top.pending_invoice_id,
            "confidence": float(top.confidence),
            "match_strategy": top.strategy,
            "status": "proposed",
        })
        if match_id:
            proposed_count += 1

    summary = (
        f"✅ *Bank-Datei verarbeitet*\n\n"
        f"📊 {saved_count} neue Bewegungen gespeichert\n"
    )
    if duplicate_count:
        summary += f"⏭ {duplicate_count} bereits importiert (uebersprungen)\n"
    summary += (
        f"🎯 {proposed_count} Match-Vorschlaege bereit\n\n"
    )
    if proposed_count > 0:
        summary += "Klick auf */review* um sie durchzugehen."
    else:
        summary += (
            "ℹ️ Keine automatischen Matches. Pruefe ob die offenen Rechnungen "
            "QR-Referenz oder IBAN haben."
        )
    await status_msg.edit_text(summary, parse_mode=ParseMode.MARKDOWN)


# Cache fuer Bexio-Banking-Account-Lookup. Bexio aendert das selten,
# deshalb einmal pro Bot-Run reicht.
_bexio_bank_accounts_cache: Optional[List[Dict[str, Any]]] = None


async def _find_bexio_bank_account_id(camt_iban: Optional[str]) -> Optional[int]:
    """
    Loest die camt-IBAN des Konto-Eigentuemers in eine Bexio-Banking-
    Account-ID auf (die wird fuer register_bill_payment gebraucht).

    Strategie:
    1. Versuch: Bexio-Banking-Account mit gleicher IBAN finden
    2. Fallback: wenn nur ein Banking-Account existiert, den nehmen
    3. Sonst: None -> Caller muss Fehler werfen
    """
    global _bexio_bank_accounts_cache
    if _bexio_bank_accounts_cache is None:
        try:
            _bexio_bank_accounts_cache = await bexio_module.bexio.list_bank_accounts()
        except Exception as e:
            logger.error(f"Bexio Banking-Accounts laden fehlgeschlagen: {e}")
            return None

    accounts = _bexio_bank_accounts_cache or []
    if not accounts:
        return None

    if camt_iban:
        normalized = camt_iban.replace(" ", "").upper()
        for a in accounts:
            iban = (a.get("iban") or "").replace(" ", "").upper()
            if iban and iban == normalized:
                return a.get("id")

    # Genau ein Konto -> nehmen
    if len(accounts) == 1:
        return accounts[0].get("id")

    return None


async def cmd_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Geht offene Match-Vorschlaege durch (einen nach dem anderen)."""
    if not await _check_auth(update):
        return

    proposals = db.get_pending_match_proposals(limit=1)
    if not proposals:
        await update.message.reply_text(
            "✅ Keine offenen Match-Vorschlaege.\n\n"
            "Schicke eine camt.054-Datei vom Online-Banking um neue zu importieren."
        )
        return

    await _show_match_proposal(update.message, proposals[0])


async def _show_match_proposal(message_or_query, proposal: Dict[str, Any]) -> None:
    """Zeigt einen einzelnen Match-Vorschlag mit Aktions-Buttons."""
    bank_tx = db.get_bank_transaction(proposal["bank_transaction_id"])
    invoice = db.get_invoice(proposal["pending_invoice_id"])

    if not bank_tx or not invoice:
        msg = "⚠️ Match-Vorschlag verweist auf geloeschte Daten."
        if hasattr(message_or_query, "edit_text"):
            await message_or_query.edit_text(msg)
        else:
            await message_or_query.reply_text(msg)
        return

    confidence_pct = int(float(proposal["confidence"]) * 100)
    conf_icon = (
        "🟢" if confidence_pct >= 90
        else "🟡" if confidence_pct >= 70
        else "🟠"
    )

    bank_amt = abs(float(bank_tx["amount"]))
    inv_amt = float(invoice.get("total_amount") or 0)
    diff = abs(bank_amt - inv_amt)
    diff_text = "" if diff < 0.01 else f" (Δ {format_chf(diff)})"

    text = (
        f"{conf_icon} *Match-Vorschlag* ({confidence_pct}%)\n\n"
        f"🏦 *Bank-Bewegung:*\n"
        f"  {format_chf(bank_amt)} an {truncate(bank_tx.get('counterparty_name') or '?', 35)}\n"
        f"  {bank_tx['booking_date']}"
    )
    qr = bank_tx.get("structured_reference")
    if qr:
        text += f"\n  QR-Ref ...{qr[-7:]}"

    text += (
        f"\n\n📄 *Offene Rechnung:*\n"
        f"  {truncate(invoice.get('vendor_name') or '?', 35)} "
        f"{format_chf(inv_amt)}{diff_text}\n"
        f"  {invoice.get('invoice_date') or '?'}"
    )
    if invoice.get("invoice_number"):
        text += f"\n  Nr {truncate(invoice['invoice_number'], 25)}"

    text += f"\n\n_Strategie: `{proposal['match_strategy']}`_"

    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Buchen",
                callback_data=f"matchbook:{proposal['id']}",
            ),
            InlineKeyboardButton(
                "⏭ Skip",
                callback_data=f"matchskip:{proposal['id']}",
            ),
        ],
    ]

    if hasattr(message_or_query, "edit_text"):
        await message_or_query.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await message_or_query.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )


async def _show_next_match_or_done(query) -> None:
    """Holt den naechsten offenen Vorschlag oder schliesst den Review-Flow."""
    next_proposals = db.get_pending_match_proposals(limit=1)
    if next_proposals:
        await _show_match_proposal(query.message, next_proposals[0])
    else:
        await query.message.reply_text(
            "✅ Alle Match-Vorschlaege durchgegangen."
        )


async def _callback_match_book(query, match_id: str) -> None:
    """User bestaetigt Match -> Payment in Bexio registrieren."""
    proposal = db.get_payment_match(match_id)
    if not proposal or proposal["status"] != "proposed":
        await query.edit_message_text("ℹ️ Match nicht mehr aktiv.")
        return

    bank_tx = db.get_bank_transaction(proposal["bank_transaction_id"])
    invoice = db.get_invoice(proposal["pending_invoice_id"])
    if not bank_tx or not invoice:
        await query.edit_message_text("❌ Bank-TX oder Rechnung fehlt.")
        db.update_payment_match_status(match_id, "failed",
                                       error_message="missing tx or invoice")
        return

    bexio_bill_id = invoice.get("bexio_bill_id")
    if not bexio_bill_id:
        await query.edit_message_text(
            "⚠️ *Rechnung noch nicht in Bexio gebucht*\n\n"
            "Erst die Lieferantenrechnung normal mit ✅ Buchen abschliessen, "
            "dann nochmal /review.",
            parse_mode=ParseMode.MARKDOWN,
        )
        # Bleibt 'proposed' fuer spaeter
        return

    bank_account_id = await _find_bexio_bank_account_id(
        bank_tx.get("bank_account_iban")
    )
    if not bank_account_id:
        await query.edit_message_text(
            "❌ *Bexio-Banking-Account nicht gefunden*\n\n"
            "Pruefe in Bexio unter Banking ob das Konto verbunden ist und "
            "eine IBAN hat die mit dem camt-File matcht.",
            parse_mode=ParseMode.MARKDOWN,
        )
        db.update_payment_match_status(match_id, "failed",
                                       error_message="no bexio bank account")
        return

    db.update_payment_match_status(match_id, "confirmed")
    await query.edit_message_text("⏳ Registriere Zahlung in Bexio…")

    try:
        result = await bexio_module.bexio.register_bill_payment(
            bill_id=str(bexio_bill_id),
            amount=abs(float(bank_tx["amount"])),
            value_date=bank_tx.get("value_date") or bank_tx["booking_date"],
            bank_account_id=int(bank_account_id),
            currency=bank_tx.get("currency") or "CHF",
        )
        bexio_payment_id = (result or {}).get("id") if result else None
        db.update_payment_match_status(
            match_id,
            "booked",
            bexio_payment_id=str(bexio_payment_id) if bexio_payment_id else None,
        )
        db.update_bank_transaction_match_status(
            proposal["bank_transaction_id"], "matched"
        )
        db.log_action(
            invoice["id"],
            "payment_registered",
            actor=f"telegram:{query.from_user.id}",
            details={
                "match_id": match_id,
                "bexio_payment_id": str(bexio_payment_id) if bexio_payment_id else None,
                "amount": abs(float(bank_tx["amount"])),
                "value_date": bank_tx.get("value_date") or bank_tx["booking_date"],
            },
        )

        await query.edit_message_text(
            f"✅ *Zahlung registriert*\n\n"
            f"Bill {truncate(str(bexio_bill_id), 12)} -> bezahlt\n"
            f"{format_chf(abs(float(bank_tx['amount'])))} am "
            f"{bank_tx.get('value_date') or bank_tx['booking_date']}",
            parse_mode=ParseMode.MARKDOWN,
        )
        await _show_next_match_or_done(query)
    except bexio_module.BexioError as e:
        db.update_payment_match_status(match_id, "failed", error_message=str(e))
        db.log_action(
            invoice["id"],
            "payment_failed",
            details={"match_id": match_id, "error": str(e)},
        )
        await query.edit_message_text(
            f"❌ *Bexio-Fehler bei Payment-Registration*\n\n"
            f"`{truncate(str(e), 300)}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def _callback_match_skip(query, match_id: str) -> None:
    """User skippt Match -> Status auf 'rejected'."""
    db.update_payment_match_status(match_id, "rejected")
    await query.edit_message_text("⏭ Match uebersprungen.")
    await _show_next_match_or_done(query)


# =========================================================
# FALLBACK FUER NORMALEN TEXT
# =========================================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Wenn User einfach Text schreibt statt Datei."""
    if not await _check_auth(update):
        return
    
    await update.message.reply_text(
        "📎 Schick mir ein PDF oder Foto einer Rechnung.\n\n"
        "Oder nutze /help fuer eine Anleitung."
    )


# =========================================================
# APP-SETUP
# =========================================================

def build_application() -> Application:
    """Erstellt die Telegram Application mit allen Handlern."""
    app = Application.builder().token(settings.telegram_bot_token).build()
    
    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("learn", cmd_learn))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("vendors", cmd_vendors))
    app.add_handler(CommandHandler("review", cmd_review))
    
    # Dateien
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    # Callbacks (Button-Klicks)
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    # Fallback
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    return app
