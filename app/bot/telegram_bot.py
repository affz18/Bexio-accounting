import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode
from app.config import settings
from app.utils.logger import setup_logger
from app.bot.auth import is_authorized
from app.bot import messages
from app.services.gemini_service import extract_invoice_data
from app.services.storage_service import upload_invoice
from app.services.supabase_client import supabase
from app.services.vendor_matcher import find_vendor
import json

logger = setup_logger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update.effective_chat.id):
        await update.message.reply_text(messages.MSG_UNAUTHORIZED)
        return
    await update.message.reply_text(messages.MSG_START)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update.effective_chat.id):
        return
    await update.message.reply_text(messages.MSG_HELP, parse_mode=ParseMode.MARKDOWN)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not await is_authorized(chat_id):
        await update.message.reply_text(messages.MSG_UNAUTHORIZED)
        return

    message = await update.message.reply_text(messages.MSG_PROCESSING)
    
    try:
        # 1. Datei herunterladen
        if update.message.document:
            file_obj = await update.message.document.get_file()
            mime_type = update.message.document.mime_type
            filename = update.message.document.file_name
        elif update.message.photo:
            file_obj = await update.message.photo[-1].get_file()
            mime_type = "image/jpeg"
            filename = "photo.jpg"
        else:
            return

        file_bytes = await file_obj.download_as_bytearray()
        
        # 2. In Supabase laden
        storage_path = await upload_invoice(bytes(file_bytes), filename, mime_type)
        
        # 3. Datenbank-Eintrag erstellen (pending_invoices)
        new_invoice = supabase.table('pending_invoices').insert({
            'status': 'pending',
            'source': 'telegram',
            'chat_id': chat_id,
            'storage_path': storage_path
        }).execute()
        invoice_db_id = new_invoice.data[0]['id']
        
        # 4. Daten mit Gemini extrahieren
        extracted = await extract_invoice_data(bytes(file_bytes), mime_type)
        
        if not extracted.is_invoice:
            await message.edit_text(messages.MSG_NOT_INVOICE)
            supabase.table('pending_invoices').update({'status': 'not_invoice'}).eq('id', invoice_db_id).execute()
            return
            
        # 5. Vendor Matching
        vendor = await find_vendor(extracted.vendor_name)
        confidence = 0.95 if vendor else 0.50
        account_nr = vendor.get('default_account_nr', 'Unbekannt') if vendor else '?'
        account_name = vendor.get('default_account_name', 'Bitte Konto wählen') if vendor else 'Neuer Lieferant'
        tax_rate = "8.1" # Standard-Annahme, könnte aus vendor kommen
        
        # Speichern der extrahierten Daten in DB
        supabase.table('pending_invoices').update({
            'extracted_data': json.loads(extracted.model_dump_json()),
            'suggested_account_id': vendor.get('default_account_id') if vendor else None,
            'confidence': confidence
        }).eq('id', invoice_db_id).execute()

        # 6. Telegram Freigabe senden
        text = messages.build_invoice_message(
            extracted.vendor_name or "Unbekannt",
            extracted.total_amount or 0.0,
            str(extracted.invoice_date) if extracted.invoice_date else "Unbekannt",
            extracted.invoice_number or "Unbekannt",
            account_nr,
            account_name,
            tax_rate,
            confidence
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ Buchen", callback_data=f"book_{invoice_db_id}")],
            [InlineKeyboardButton("📝 Anderes Konto", callback_data=f"change_{invoice_db_id}")],
            [InlineKeyboardButton("❌ Verwerfen", callback_data=f"reject_{invoice_db_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Fehler bei Dokumentverarbeitung: {e}", exc_info=True)
        await message.edit_text(messages.MSG_ERROR.format(error=str(e)))


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    action, invoice_id = data.split('_')
    
    if action == "reject":
        supabase.table('pending_invoices').update({'status': 'rejected'}).eq('id', invoice_id).execute()
        await query.edit_message_text(text="❌ Rechnung wurde verworfen.")
        
    elif action == "book":
        await query.edit_message_text(text="⏳ Verbuche in Bexio...")
        # Hier würde die API-Verbindung zu Bexio initiiert
        # Für den POC mocken wir den Erfolg
        supabase.table('pending_invoices').update({
            'status': 'booked',
            'bexio_bill_id': 9999 # mock
        }).eq('id', invoice_id).execute()
        await query.edit_message_text(text="✅ *Erfolgreich gebucht!*\nBexio Bill ID: 9999", parse_mode=ParseMode.MARKDOWN)
        
    elif action == "change":
        await query.edit_message_text(text="Konto-Auswahl ist im POC noch nicht vollständig implementiert. Bitte bestätige ✅ oder ❌.")

def setup_telegram_app() -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_document))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    return app
