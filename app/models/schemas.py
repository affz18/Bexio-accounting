from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date

class InvoiceExtractionResult(BaseModel):
    is_invoice: bool = Field(description="Ist das hochgeladene Dokument eine Rechnung?")
    vendor_name: Optional[str] = Field(None, description="Name des Lieferanten/Verkäufers")
    invoice_number: Optional[str] = Field(None, description="Rechnungsnummer")
    invoice_date: Optional[date] = Field(None, description="Rechnungsdatum im Format YYYY-MM-DD")
    due_date: Optional[date] = Field(None, description="Fälligkeitsdatum im Format YYYY-MM-DD")
    total_amount: Optional[float] = Field(None, description="Rechnungsbetrag (Brutto)")
    vat_amount: Optional[float] = Field(None, description="Enthaltener Mehrwertsteuerbetrag")
    iban: Optional[str] = Field(None, description="IBAN für die Zahlung (beginnt oft mit CH)")
    reference_number: Optional[str] = Field(None, description="QR-Referenznummer (27-stellig ohne Leerzeichen)")
    currency: Optional[str] = Field(None, description="Währung (z.B. CHF, EUR)")
