import google.generativeai as genai
from pydantic import ValidationError
import json
from app.config import settings
from app.utils.logger import setup_logger
from app.models.schemas import InvoiceExtractionResult

logger = setup_logger(__name__)

# Konfiguration von Gemini API
genai.configure(api_key=settings.gemini_api_key)

SYSTEM_PROMPT = """Du bist ein hochpräziser Buchhaltungs-Assistent für Schweizer Unternehmen.
Deine Aufgabe ist es, Rechnungen aus Bildern oder PDFs zu analysieren und strukturierte Daten zu extrahieren.
WICHTIG:
1. Prüfe zuerst, ob das Dokument wirklich eine Rechnung (oder Quittung/Kassenbon) ist. Falls nicht, setze is_invoice auf false.
2. Achte besonders auf Schweizer Eigenheiten: Währung ist oft CHF, MwSt-Satz meist 8.1% (oder 2.6% / 0%), IBAN beginnt meist mit CH, ESR/QR-Referenznummer.
3. Wenn ein Wert nicht sicher erkennbar ist, gib null zurück, anstatt zu raten.
4. Beträge müssen als float ohne Währungssymbol zurückgegeben werden.
5. Die Antwort muss zwingend ein valides JSON-Objekt sein, das genau folgendem Schema entspricht.
"""

class GeminiError(Exception):
    pass

async def extract_invoice_data(file_data: bytes, mime_type: str) -> InvoiceExtractionResult:
    """Extrahiert Rechnungsdaten aus Bytes via Gemini API."""
    try:
        model = genai.GenerativeModel(
            model_name=settings.gemini_model,
            system_instruction=SYSTEM_PROMPT,
        )
        
        prompt = "Bitte extrahiere die Rechnungsdaten aus diesem Dokument als JSON."
        content = [
            prompt,
            {
                "mime_type": mime_type,
                "data": file_data
            }
        ]
        
        # Schema anfordern, wir übergeben format='json' und das schema (falls unterstützt)
        # Besser wir erzwingen JSON:
        response = model.generate_content(
            content,
            generation_config=import_generative_models_schemas()
        )
        
        try:
            # Versuche den String zu parsen
            raw_text = response.text
            # Manchmal ist der JSON-String in Markdown-Code-Blöcken
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:-3]
            elif raw_text.startswith("```"):
                raw_text = raw_text[3:-3]
                
            data = json.loads(raw_text.strip())
            return InvoiceExtractionResult(**data)
            
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error(f"Fehler beim Parsen der Gemini Antwort: {e}")
            raise GeminiError(f"Ungültiges Format von Gemini: {e}")
            
    except Exception as e:
        logger.error(f"Gemini API Fehler: {e}")
        raise GeminiError(f"Fehler bei der Gemini-Kommunikation: {e}")

def import_generative_models_schemas():
    return genai.GenerationConfig(
        response_mime_type="application/json",
        response_schema=InvoiceExtractionResult
    )
