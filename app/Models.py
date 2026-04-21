"""
Pydantic-Modelle fuer strukturierte Daten.
Wird von Gemini-Service fuer Extraktion und von Bexio-Service fuer Buchungen genutzt.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date as date_type


class InvoiceExtractionResult(BaseModel):
    """
    Das Schema, das Gemini zurueckgeben MUSS, wenn es eine Rechnung analysiert.
    Alle Felder ausser is_invoice sind Optional, damit Gemini null zurueckgeben kann
    falls es unsicher ist.
    """
    is_invoice: bool = Field(
        description="True wenn Dokument eine Rechnung/Quittung ist, sonst False"
    )
    vendor_name: Optional[str] = Field(
        None,
        description="Name des Lieferanten/Verkaeufers (z.B. 'Swisscom AG')"
    )
    invoice_number: Optional[str] = Field(
        None,
        description="Rechnungsnummer des Lieferanten"
    )
    invoice_date: Optional[str] = Field(
        None,
        description="Rechnungsdatum im Format YYYY-MM-DD"
    )
    due_date: Optional[str] = Field(
        None,
        description="Faelligkeitsdatum im Format YYYY-MM-DD"
    )
    total_amount: Optional[float] = Field(
        None,
        description="Rechnungsbetrag Brutto (mit MwSt)"
    )
    vat_amount: Optional[float] = Field(
        None,
        description="Enthaltener MwSt-Betrag in CHF"
    )
    vat_rate: Optional[float] = Field(
        None,
        description="MwSt-Satz in Prozent (z.B. 8.1 fuer 8.1%)"
    )
    currency: Optional[str] = Field(
        None,
        description="Waehrung, Default CHF"
    )
    iban: Optional[str] = Field(
        None,
        description="IBAN fuer die Zahlung (beginnt meist mit CH)"
    )
    reference_number: Optional[str] = Field(
        None,
        description="QR-Referenznummer (27-stellig) oder ESR-Nummer"
    )
    uid_number: Optional[str] = Field(
        None,
        description="Schweizer UID-Nummer des Lieferanten (Format CHE-XXX.XXX.XXX)"
    )
    
    def to_summary(self) -> str:
        """Kurze menschenlesbare Zusammenfassung."""
        from app.utils import format_chf
        return (
            f"{self.vendor_name or 'Unbekannter Lieferant'} – "
            f"{format_chf(self.total_amount)} – "
            f"{self.invoice_date or '?'}"
        )


class BexioAccount(BaseModel):
    """Ein Konto aus dem Bexio-Kontenplan."""
    id: int
    account_no: str
    name: str
    account_type: Optional[int] = None
    is_active: bool = True


class BexioTax(BaseModel):
    """Ein MwSt-Satz aus Bexio."""
    id: int
    code: str
    name: str
    value: float  # Prozent-Satz, z.B. 8.1
    type: Optional[str] = None  # "pre_tax" oder "sales_tax"


class BexioContact(BaseModel):
    """Ein Kontakt/Lieferant aus Bexio."""
    id: int
    name_1: str
    name_2: Optional[str] = None
    contact_type_id: int  # 1 = Person, 2 = Firma
    
    @property
    def display_name(self) -> str:
        if self.name_2:
            return f"{self.name_1} {self.name_2}"
        return self.name_1


class VendorMemory(BaseModel):
    """Repraesentation eines gelernten Lieferanten aus Supabase."""
    id: str
    name: str
    normalized_name: str
    bexio_contact_id: Optional[int] = None
    default_account_id: Optional[int] = None
    default_account_nr: Optional[str] = None
    default_tax_id: Optional[int] = None
    default_tax_rate: Optional[float] = None
    booking_count: int = 0
    confidence_score: float = 0.0
    iban: Optional[str] = None
    uid_nummer: Optional[str] = None
