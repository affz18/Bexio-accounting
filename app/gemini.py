"""
Gemini API Integration - extrahiert strukturierte Rechnungsdaten aus PDFs/Bildern.

Nutzt die NEUE google-genai Library (NICHT google-generativeai, die ist deprecated).
Dokumentation: https://googleapis.github.io/python-genai/
"""
import asyncio
import json
from typing import Optional, Tuple

from google import genai
from google.genai import types
from pydantic import ValidationError

from app.config import settings
from app.models import InvoiceExtractionResult
from app.utils import setup_logger


logger = setup_logger(__name__)


class GeminiError(Exception):
    """Fehler bei der Gemini-Extraktion."""
    pass


# =========================================================
# SYSTEM-PROMPT (Deutsch, Schweizer Kontext)
# =========================================================

SYSTEM_PROMPT = """Du bist ein hochpraeziser Buchhaltungs-Assistent fuer Schweizer Unternehmen.

Deine Aufgabe: Analysiere das hochgeladene Dokument und extrahiere strukturierte Rechnungsdaten.

## WICHTIGE REGELN

1. **Erst pruefen was es ist:** Setze `is_invoice` auf true NUR wenn das Dokument eine Rechnung, Quittung oder Kassenbon ist. Bei Werbung, Briefen, Lieferscheinen, Mahnungen etc. setze es auf false.

2. **Bei Unsicherheit: null, nicht raten.** Lieber ein Feld leer lassen als falsche Daten liefern. Der User kann fehlende Daten ergaenzen, aber falsche Daten sind schlimmer.

3. **Schweizer Kontext beachten:**
   - Waehrung ist fast immer CHF (manchmal EUR bei Auslands-Lieferanten)
   - MwSt-Saetze: 8.1% (Normalsatz), 2.6% (reduziert), 3.8% (Beherbergung), 0% (steuerfrei)
   - IBAN beginnt mit "CH" und hat 21 Zeichen (ohne Leerzeichen)
   - UID-Nummer Format: CHE-XXX.XXX.XXX
   - QR-Referenz: 27-stellig, nur Ziffern, bei neuen QR-Rechnungen
   - ESR-Referenz: 27-stellig (alte Orange Einzahlungsscheine)

4. **Datumsformat:** Immer YYYY-MM-DD zurueckgeben, nie DD.MM.YYYY.
   Beispiel: "15. Maerz 2026" oder "15.03.2026" -> "2026-03-15"

5. **Betraege:** Nur Zahlen, keine Waehrungssymbole, keine Tausender-Trennzeichen.
   Beispiel: "CHF 1'234.50" -> 1234.50

6. **Lieferanten-Name (vendor_name):** Der NAME des Unternehmens das die Rechnung stellt,
   nicht der Empfaenger. Nimm den Haupt-Firmennamen, keine Zusaetze wie "AG" weglassen.
   Beispiel: "Swisscom (Schweiz) AG" -> "Swisscom (Schweiz) AG"

7. **MwSt-Extraktion:**
   - `vat_amount` = der ausgewiesene MwSt-Betrag in CHF (z.B. 98.50)
   - `vat_rate` = der prozentuale Satz (z.B. 8.1)
   - Wenn mehrere Saetze auf der Rechnung: den hoechsten Anteil nehmen

8. **Rueckgabe immer als valides JSON** entsprechend dem Schema.
"""


# =========================================================
# JSON-SCHEMA FUER GEMINI
# =========================================================

# Gemini's Structured Output erwartet ein OpenAPI-Schema.
# Wir definieren es manuell, weil das robuster ist als Pydantic->JSON-Schema.
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "is_invoice": {
            "type": "BOOLEAN",
            "description": "True wenn Dokument eine Rechnung/Quittung ist"
        },
        "vendor_name": {
            "type": "STRING",
            "description": "Name des Lieferanten (Firma die Rechnung stellt)",
            "nullable": True
        },
        "invoice_number": {
            "type": "STRING",
            "description": "Rechnungsnummer des Lieferanten",
            "nullable": True
        },
        "invoice_date": {
            "type": "STRING",
            "description": "Rechnungsdatum im Format YYYY-MM-DD",
            "nullable": True
        },
        "due_date": {
            "type": "STRING",
            "description": "Faelligkeitsdatum im Format YYYY-MM-DD",
            "nullable": True
        },
        "total_amount": {
            "type": "NUMBER",
            "description": "Rechnungsbetrag Brutto in Zahlen",
            "nullable": True
        },
        "vat_amount": {
            "type": "NUMBER",
            "description": "Ausgewiesener MwSt-Betrag in CHF",
            "nullable": True
        },
        "vat_rate": {
            "type": "NUMBER",
            "description": "MwSt-Satz in Prozent (z.B. 8.1)",
            "nullable": True
        },
        "currency": {
            "type": "STRING",
            "description": "Waehrungscode, z.B. CHF oder EUR",
            "nullable": True
        },
        "iban": {
            "type": "STRING",
            "description": "IBAN fuer Zahlung (beginnt mit CH)",
            "nullable": True
        },
        "reference_number": {
            "type": "STRING",
            "description": "QR- oder ESR-Referenznummer (27-stellig)",
            "nullable": True
        },
        "uid_number": {
            "type": "STRING",
            "description": "UID-Nummer des Lieferanten (CHE-XXX.XXX.XXX)",
            "nullable": True
        }
    },
    "required": ["is_invoice"]
}


# =========================================================
# CLIENT (Singleton)
# =========================================================

_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    """Lazy-Init des Gemini Clients."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
        logger.info(f"Gemini Client initialisiert (Model: {settings.gemini_model})")
    return _client


# =========================================================
# HAUPT-EXTRAKTION
# =========================================================

async def extract_invoice(
    file_bytes: bytes,
    mime_type: str = "application/pdf",
) -> InvoiceExtractionResult:
    """
    Extrahiert Rechnungsdaten aus einem PDF oder Bild via Gemini.
    
    Args:
        file_bytes: Die Datei als bytes
        mime_type: MIME-Typ (application/pdf, image/jpeg, image/png, image/heic)
    
    Returns:
        InvoiceExtractionResult mit den extrahierten Daten.
    
    Raises:
        GeminiError: Bei API-Fehlern oder ungueltiger Response.
    """
    if not file_bytes:
        raise GeminiError("Leere Datei erhalten")
    
    try:
        # Gemini's Python SDK ist synchron, wir wrappen in asyncio.to_thread
        # damit der Event-Loop nicht blockiert
        result = await asyncio.to_thread(
            _extract_sync,
            file_bytes,
            mime_type,
        )
        return result
    except GeminiError:
        raise  # bereits sauber, weitergeben
    except Exception as e:
        logger.exception(f"Unerwarteter Fehler bei Gemini-Extraktion: {e}")
        raise GeminiError(f"Extraktion fehlgeschlagen: {e}")


def _extract_sync(file_bytes: bytes, mime_type: str) -> InvoiceExtractionResult:
    """Synchrone Extraktion - wird von extract_invoice in Thread gewrappt."""
    client = _get_client()
    
    # File-Part fuer Gemini bauen
    file_part = types.Part.from_bytes(
        data=file_bytes,
        mime_type=mime_type,
    )
    
    user_prompt = (
        "Analysiere dieses Dokument. Extrahiere die Rechnungsdaten gemaess Schema. "
        "Falls es keine Rechnung ist, setze is_invoice auf false."
    )
    
    # Request an Gemini
    try:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[file_part, user_prompt],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
                temperature=0.1,  # deterministischer fuer Extraktionen
                max_output_tokens=2048,
            ),
        )
    except Exception as e:
        logger.error(f"Gemini API-Call fehlgeschlagen: {e}")
        raise GeminiError(f"Gemini API-Fehler: {e}")
    
    # Response parsen
    raw_text = response.text
    if not raw_text:
        raise GeminiError("Gemini hat leere Response zurueckgegeben")
    
    logger.debug(f"Gemini Raw-Response: {raw_text[:500]}")
    
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error(f"Ungueltiges JSON von Gemini: {raw_text[:300]}")
        raise GeminiError(f"Gemini lieferte ungueltiges JSON: {e}")
    
    # Post-Processing der Werte (Normalisierung)
    data = _normalize_extracted_data(data)
    
    # In Pydantic-Model giessen (final validierung)
    try:
        result = InvoiceExtractionResult(**data)
    except ValidationError as e:
        logger.error(f"Pydantic-Validierung fehlgeschlagen: {e}")
        raise GeminiError(f"Extrahierte Daten passen nicht zum Schema: {e}")
    
    # Logging fuer Monitoring
    if result.is_invoice:
        logger.info(
            f"Rechnung extrahiert: {result.vendor_name or '?'} | "
            f"{result.total_amount or '?'} {result.currency or 'CHF'} | "
            f"{result.invoice_date or '?'}"
        )
    else:
        logger.info("Dokument ist keine Rechnung (is_invoice=false)")
    
    return result


def _normalize_extracted_data(data: dict) -> dict:
    """
    Putzt die Daten bevor sie ins Pydantic-Model gehen.
    - IBAN ohne Leerzeichen und uppercase
    - QR-Referenz ohne Leerzeichen
    - Waehrung uppercase
    - Standard-Waehrung CHF wenn nicht gesetzt aber is_invoice=true
    """
    if data.get("iban"):
        data["iban"] = str(data["iban"]).replace(" ", "").upper()
    
    if data.get("reference_number"):
        data["reference_number"] = str(data["reference_number"]).replace(" ", "")
    
    if data.get("currency"):
        data["currency"] = str(data["currency"]).upper()
    elif data.get("is_invoice") is True and data.get("total_amount") is not None:
        # Default bei Schweizer Rechnungen
        data["currency"] = "CHF"
    
    if data.get("uid_number"):
        # UID normalisieren: CHE-123456789 oder CHE123.456.789 -> CHE-123.456.789
        uid = str(data["uid_number"]).upper().replace(" ", "")
        if uid.startswith("CHE") and len(uid.replace("-", "").replace(".", "")) == 12:
            # Format standardisieren
            digits = uid.replace("CHE", "").replace("-", "").replace(".", "")
            if len(digits) == 9:
                data["uid_number"] = f"CHE-{digits[:3]}.{digits[3:6]}.{digits[6:9]}"
    
    # Betraege: falls String, zu float parsen
    for field in ("total_amount", "vat_amount", "vat_rate"):
        val = data.get(field)
        if isinstance(val, str):
            try:
                # Apostrophe und Leerzeichen raus, Komma zu Punkt
                cleaned = val.replace("'", "").replace(" ", "").replace(",", ".")
                data[field] = float(cleaned)
            except ValueError:
                logger.warning(f"Konnte '{val}' nicht zu float parsen, setze null")
                data[field] = None
    
    return data


# =========================================================
# OPTIONAL: KONTO-VORSCHLAG VIA GEMINI
# =========================================================

async def suggest_account(
    vendor_name: str,
    total_amount: float,
    available_accounts: list[dict],
) -> Tuple[Optional[int], float, str]:
    """
    Laesst Gemini einen Konto-Vorschlag machen wenn der Vendor unbekannt ist.
    
    Args:
        vendor_name: Name des Lieferanten
        total_amount: Rechnungsbetrag
        available_accounts: Liste von Konten aus Bexio
            [{"account_nr": "4400", "account_name": "Materialaufwand", "bexio_account_id": 123}, ...]
    
    Returns:
        Tuple (bexio_account_id, confidence_0_bis_1, reasoning)
    """
    if not available_accounts:
        return None, 0.0, "Keine Konten verfuegbar"
    
    # Accounts als Text fuer Prompt
    account_list = "\n".join(
        f"- {a['account_nr']}: {a['account_name']} (id={a['bexio_account_id']})"
        for a in available_accounts
    )
    
    prompt = f"""Ein Schweizer Unternehmen hat eine Rechnung erhalten:

Lieferant: {vendor_name}
Betrag: CHF {total_amount:.2f}

Verfuegbare Aufwandskonten:
{account_list}

Schlage EIN passendes Konto vor. Antworte NUR mit JSON:
{{
  "bexio_account_id": <id>,
  "confidence": <0.0 bis 1.0>,
  "reasoning": "<kurze Begruendung auf Deutsch>"
}}
"""
    
    try:
        result = await asyncio.to_thread(_suggest_sync, prompt)
        return (
            result.get("bexio_account_id"),
            float(result.get("confidence", 0.5)),
            result.get("reasoning", ""),
        )
    except Exception as e:
        logger.error(f"Konto-Vorschlag fehlgeschlagen: {e}")
        return None, 0.0, f"Fehler: {e}"


def _suggest_sync(prompt: str) -> dict:
    """Synchroner Teil des Vorschlag-Calls."""
    client = _get_client()
    
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
            max_output_tokens=512,
        ),
    )
    
    try:
        return json.loads(response.text)
    except json.JSONDecodeError:
        return {}
