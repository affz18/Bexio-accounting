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
from typing import Optional
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
        "Schick mir eine Rechnung als PDF oder Foto und ich verbuche sie in Bexio.\n\n"
        "*Befehle:*\n"
        "/sync — Bexio-Kontenplan aktualisieren\n"
        "/stats — Statistik anzeigen\n"
        "/vendors — Gelernte Lieferanten\n"
        "/help — Hilfe\n\n"
        "_Tipp: Erster Schritt ist `/sync` damit ich deinen Kontenplan kenne._",
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
    """PDF oder Bild als Document empfangen."""
    if not await _check_auth(update):
        return
    
    doc: Document = update.message.document
    
    # Validierung
    if doc.file_size and doc.file_size > 10 * 1024 * 1024:
        await update.message.reply_text("❌ Datei zu gross (max 10 MB).")
        return
    
    mime = doc.mime_type or "application/octet-stream"
    supported = ("application/pdf", "image/jpeg", "image/png", "image/jpg", "image/heic", "image/heif")
    
    if mime not in supported:
        await update.message.reply_text(
            f"❌ Dateityp `{mime}` nicht unterstuetzt.\n"
            "Schick PDF, JPG, PNG oder HEIC.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    
    await _process_invoice_file(
        update=update,
        context=context,
        file_id=doc.file_id,
        filename=doc.file_name or "document.pdf",
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
    """Gemeinsamer Workflow fuer Document und Photo."""
    chat_id = update.effective_chat.id
    
    # 1. Bestaetigung zeigen
    status_msg = await update.message.reply_text(
        f"📄 Beleg empfangen ({truncate(filename, 40)})\n"
        f"⏳ Lade herunter und analysiere…"
    )
    
    try:
        # 2. Datei von Telegram holen
        tg_file = await context.bot.get_file(file_id)
        file_bytes = await tg_file.download_as_bytearray()
        file_bytes = bytes(file_bytes)
        
        # 3. In Supabase Storage speichern
        storage_path = storage.upload_invoice_file(
            file_bytes=file_bytes,
            original_filename=filename,
            mime_type=mime_type,
        )
        if not storage_path:
            await status_msg.edit_text("❌ Fehler beim Speichern der Datei.")
            return
        
        # 4. Pending-Invoice Eintrag
        invoice_id = db.create_pending_invoice(
            source="telegram",
            source_reference=str(update.message.message_id),
            file_path=storage_path,
            original_filename=filename,
            file_size_bytes=file_size,
            file_mime_type=mime_type,
        )
        if not invoice_id:
            await status_msg.edit_text("❌ Fehler beim DB-Eintrag.")
            return
        
        db.log_action(invoice_id, "received", actor=f"telegram:{chat_id}", details={
            "filename": filename,
            "mime_type": mime_type,
            "size": file_size,
        })
        
        # 5. Gemini-Extraktion
        await status_msg.edit_text("🧠 Gemini analysiert das Dokument…")
        
        try:
            result = await gemini.extract_invoice(file_bytes, mime_type)
        except gemini.GeminiError as e:
            db.mark_invoice_failed(invoice_id, f"Gemini-Fehler: {e}")
            db.log_action(invoice_id, "extraction_failed", details={"error": str(e)})
            await status_msg.edit_text(
                f"❌ *Extraktion fehlgeschlagen*\n\n`{truncate(str(e), 200)}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        # 6. Ist es eine Rechnung?
        if not result.is_invoice:
            db.update_invoice_extraction(
                invoice_id=invoice_id,
                extracted_data=result.model_dump(),
                status="not_invoice",
            )
            db.log_action(invoice_id, "not_invoice")
            await status_msg.edit_text(
                "🤔 Das sieht nicht nach einer Rechnung aus.\n"
                "Ich ignoriere das Dokument."
            )
            return
        
        # 7. Extrahierte Daten speichern
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
        
        # 8. Vendor-Matching + Vorschlag bauen
        await _show_suggestion(
            status_msg=status_msg,
            invoice_id=invoice_id,
            result=result,
        )
    
    except Exception as e:
        logger.exception(f"Unerwarteter Fehler beim Datei-Processing: {e}")
        await status_msg.edit_text(
            f"❌ *Unerwarteter Fehler*\n\n`{truncate(str(e), 200)}`",
            parse_mode=ParseMode.MARKDOWN,
        )


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
            InlineKeyboardButton(
                "🧾 Privat bezahlt",
                callback_data=f"bookpriv:{invoice_id}",
            ),
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
    
    if data.startswith("bookpriv:"):
        invoice_id = data.split(":", 1)[1]
        await _callback_book_private(query, invoice_id)
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


async def _callback_book_private(query, invoice_id: str) -> None:
    """
    User klickt auf 'Privat bezahlt'. Buchung als direkter Manual-Journal-
    Entry: Aufwand an Kontokorrent Inhaber (z.B. 2100). Keine Lieferanten-
    Rechnung wird erstellt - es gibt keine offene Verbindlichkeit gegen
    einen Dritten, weil der Inhaber selber gezahlt hat.
    """
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        await query.edit_message_text("❌ Beleg nicht gefunden.")
        return

    if invoice.get("status") in ("booked", "booked_private"):
        await query.edit_message_text("ℹ️ Schon gebucht.")
        return

    # Soll-Konto: das vorgeschlagene Aufwand-Konto
    debit_account_id = invoice.get("suggested_account_id")
    if not debit_account_id:
        await query.edit_message_text(
            "❌ *Kein Aufwand-Konto vorgeschlagen.*\n\n"
            "Klicke erst `📝 Anderes Konto` und waehle ein Konto, "
            "dann nochmal `🧾 Privat bezahlt`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Haben-Konto: Kontokorrent Inhaber - aus Settings via Konto-Nr
    credit_account_nr = settings.bexio_private_payment_credit_account_nr
    credit_account = db.get_account_by_nr(credit_account_nr)
    if not credit_account or not credit_account.get("bexio_account_id"):
        await query.edit_message_text(
            f"❌ *Konto {credit_account_nr} nicht im Cache.*\n\n"
            f"Fuehre `/sync` aus damit der Bot den Kontenplan kennt. "
            f"Falls Konto {credit_account_nr} in Bexio nicht existiert, "
            f"setze `BEXIO_PRIVATE_PAYMENT_CREDIT_ACCOUNT_NR` auf eure "
            f"Kontokorrent-Inhaber-Konto-Nr.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    credit_account_id = credit_account["bexio_account_id"]

    total = invoice.get("total_amount")
    if total is None:
        await query.edit_message_text("❌ Betrag fehlt.")
        return

    # Buchungsdatum: Belegdatum, sonst heute
    today_iso = datetime.now(timezone.utc).date().isoformat()
    booking_date = invoice.get("invoice_date") or today_iso

    vendor = invoice.get("vendor_name") or "Unbekannt"
    description = (
        f"Beleg {truncate(vendor, 40)} {booking_date} - "
        f"privat durch Inhaber bezahlt"
    )

    await query.edit_message_text(
        "⏳ Buche als 'privat bezahlt' in Bexio…",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        result = await bexio_module.bexio.create_manual_journal_entry(
            date=booking_date,
            debit_account_id=int(debit_account_id),
            credit_account_id=int(credit_account_id),
            amount=float(total),
            description=description,
            tax_id=invoice.get("suggested_tax_id"),
            reference_nr=invoice.get("invoice_number"),
        )
        if not result:
            await query.edit_message_text(
                "❌ Buchung fehlgeschlagen (siehe Logs)."
            )
            return

        manual_entry_id = result.get("id") or "?"
        db.mark_invoice_booked_private(invoice_id, str(manual_entry_id))
        db.log_action(
            invoice_id,
            "booked_private",
            actor=f"telegram:{query.from_user.id}",
            details={
                "bexio_manual_entry_id": str(manual_entry_id),
                "debit_account_id": int(debit_account_id),
                "credit_account_id": int(credit_account_id),
                "credit_account_nr": credit_account_nr,
                "amount": float(total),
            },
        )

        await query.edit_message_text(
            f"✅ *Privat bezahlt - Buchung erfasst*\n\n"
            f"Manual Entry #{manual_entry_id}\n"
            f"{vendor}\n"
            f"{format_chf(total)}\n\n"
            f"_Soll: Konto {invoice.get('suggested_account_nr') or '?'} · "
            f"Haben: {credit_account_nr} {credit_account.get('account_name') or ''}_",
            parse_mode=ParseMode.MARKDOWN,
        )
    except bexio_module.BexioError as e:
        db.mark_invoice_failed(invoice_id, str(e))
        db.log_action(invoice_id, "booking_private_failed", details={"error": str(e)})
        await query.edit_message_text(
            f"❌ *Bexio-Fehler bei Privat-Buchung*\n\n"
            f"`{truncate(str(e), 300)}`",
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
    
    # Datumsfelder
    today = datetime.now(timezone.utc).date()
    bill_date = invoice.get("invoice_date") or today.isoformat()
    due_date = invoice.get("due_date") or (today + timedelta(days=30)).isoformat()
    
    # Bill erstellen
    bill = await bexio_module.bexio.create_supplier_bill(
        vendor_bexio_id=bexio_contact_id,
        vendor_reference=invoice.get("invoice_number") or "—",
        bill_date=bill_date,
        due_date=due_date,
        total_amount=float(total),
        account_id=int(account_id),
        tax_id=invoice.get("suggested_tax_id"),
        currency_code=invoice.get("currency") or "CHF",
        title=f"Rechnung {vendor_name}",
        iban=invoice.get("iban"),
        qr_reference=invoice.get("reference_number"),
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
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("vendors", cmd_vendors))
    
    # Dateien
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    # Callbacks (Button-Klicks)
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    # Fallback
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    return app
