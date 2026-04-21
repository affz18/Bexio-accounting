MSG_UNAUTHORIZED = "Leider bist du nicht berechtigt, diesen Bot zu nutzen. Bitte wende dich an den Administrator."
MSG_START = "👋 Grüessech! Ich bin der VisioSkin Accounting Agent.\nSende mir einfach Rechnungen (als PDF oder Foto) und ich bereite die Verbuchung in Bexio vor."
MSG_HELP = "📄 *So funktioniert's:*\n1. Sende mir ein PDF oder Bild einer Rechnung.\n2. Ich extrahiere die Daten (Lieferant, Betrag, MwSt, etc.).\n3. Du bestätigst die Daten und das Konto.\n4. Ich verbuche es in Bexio!\n\n_Befehle:_\n/stats - Zeigt Statistiken\n/vendors - Gelernte Lieferanten"
MSG_PROCESSING = "📄 Beleg empfangen. Ich analysiere die Daten, bitte einen Moment Geduld..."
MSG_NOT_INVOICE = "Das sieht nicht nach einer Rechnung aus. Datei wurde ignoriert."
MSG_ERROR = "❌ Es ist ein Fehler aufgetreten: {error}"

def build_invoice_message(vendor_name: str, total: float, date: str, num: str, account_nr: str, account_name: str, tax_rate: str, confidence: float) -> str:
    return f"""📄 *Rechnung erkannt*
    
🏢 Lieferant: {vendor_name}
💰 Betrag: CHF {total}
📅 Datum: {date}
🔢 Nr: {num}

💡 Vorschlag: Konto {account_nr} – {account_name}
🏷 MwSt: {tax_rate}%
📊 Konfidenz: {confidence}
"""
