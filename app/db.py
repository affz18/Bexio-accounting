"""
Supabase Database Wrapper.
Kapselt alle DB-Operationen. Der Rest des Codes ruft nur diese Funktionen auf.
"""
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from uuid import UUID

from supabase import create_client, Client

from app.config import settings
from app.utils import setup_logger, normalize_vendor_name
from app.models import VendorMemory


logger = setup_logger(__name__)


# Singleton-Client - einmal initialisiert, ueberall genutzt
_client: Optional[Client] = None


def get_client() -> Client:
    """Lazy-init des Supabase-Clients. Wird beim ersten Aufruf erstellt."""
    global _client
    if _client is None:
        _client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key
        )
        logger.info("Supabase Client initialisiert")
    return _client


# =========================================================
# AUTHORIZED USERS
# =========================================================

def is_user_authorized(telegram_chat_id: int) -> bool:
    """Prueft ob ein User den Bot nutzen darf (via DB)."""
    try:
        result = (
            get_client()
            .table("authorized_users")
            .select("id")
            .eq("telegram_chat_id", telegram_chat_id)
            .limit(1)
            .execute()
        )
        return len(result.data) > 0
    except Exception as e:
        logger.error(f"Fehler beim Auth-Check: {e}")
        return False


def get_user_settings(telegram_chat_id: int) -> Optional[Dict[str, Any]]:
    """Holt die User-Settings (kann_auto_book etc.)."""
    try:
        result = (
            get_client()
            .table("authorized_users")
            .select("*")
            .eq("telegram_chat_id", telegram_chat_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Fehler beim Laden User-Settings: {e}")
        return None


# =========================================================
# VENDORS (Lieferanten-Memory)
# =========================================================

def find_vendor_by_name(name: str) -> Optional[VendorMemory]:
    """Sucht einen Lieferanten ueber den normalisierten Namen."""
    normalized = normalize_vendor_name(name)
    if not normalized:
        return None
    
    try:
        result = (
            get_client()
            .table("vendors")
            .select("*")
            .eq("normalized_name", normalized)
            .limit(1)
            .execute()
        )
        if result.data:
            return VendorMemory(**result.data[0])
        return None
    except Exception as e:
        logger.error(f"Fehler beim Vendor-Lookup '{name}': {e}")
        return None


def find_vendor_by_iban(iban: str) -> Optional[VendorMemory]:
    """Fallback-Suche ueber IBAN falls Name nicht exakt matcht."""
    if not iban:
        return None
    
    # IBAN normalisieren (Leerzeichen weg, uppercase)
    clean_iban = iban.replace(" ", "").upper()
    
    try:
        result = (
            get_client()
            .table("vendors")
            .select("*")
            .eq("iban", clean_iban)
            .limit(1)
            .execute()
        )
        if result.data:
            return VendorMemory(**result.data[0])
        return None
    except Exception as e:
        logger.error(f"Fehler beim IBAN-Lookup: {e}")
        return None


def create_vendor(
    name: str,
    bexio_contact_id: Optional[int] = None,
    default_account_id: Optional[int] = None,
    default_account_nr: Optional[str] = None,
    default_tax_id: Optional[int] = None,
    default_tax_rate: Optional[float] = None,
    iban: Optional[str] = None,
    uid_nummer: Optional[str] = None,
) -> Optional[VendorMemory]:
    """Legt einen neuen Lieferanten in der Memory an."""
    try:
        payload = {
            "name": name,
            "normalized_name": normalize_vendor_name(name),
            "bexio_contact_id": bexio_contact_id,
            "default_account_id": default_account_id,
            "default_account_nr": default_account_nr,
            "default_tax_id": default_tax_id,
            "default_tax_rate": default_tax_rate,
            "iban": iban.replace(" ", "").upper() if iban else None,
            "uid_nummer": uid_nummer,
            "booking_count": 0,
            "confidence_score": 0.0,
        }
        # None-Werte rausfiltern damit DB-Defaults greifen
        payload = {k: v for k, v in payload.items() if v is not None}
        
        result = (
            get_client()
            .table("vendors")
            .insert(payload)
            .execute()
        )
        if result.data:
            logger.info(f"Neuer Vendor angelegt: {name}")
            return VendorMemory(**result.data[0])
        return None
    except Exception as e:
        logger.error(f"Fehler beim Erstellen von Vendor '{name}': {e}")
        return None


def update_vendor_mapping(
    vendor_id: str,
    account_id: int,
    account_nr: str,
    tax_id: Optional[int] = None,
    tax_rate: Optional[float] = None,
) -> bool:
    """
    Aktualisiert das gelernte Konto-Mapping eines Vendors.
    Erhoeht auch booking_count und confidence_score.
    """
    try:
        # Erst aktuelle Werte holen fuer Increment
        current = (
            get_client()
            .table("vendors")
            .select("booking_count")
            .eq("id", vendor_id)
            .limit(1)
            .execute()
        )
        current_count = current.data[0]["booking_count"] if current.data else 0
        new_count = current_count + 1
        
        # Confidence waechst mit Anzahl gleicher Buchungen (bis max 0.99)
        new_confidence = min(0.50 + (new_count * 0.10), 0.99)
        
        payload = {
            "default_account_id": account_id,
            "default_account_nr": account_nr,
            "default_tax_id": tax_id,
            "default_tax_rate": tax_rate,
            "booking_count": new_count,
            "confidence_score": new_confidence,
            "last_booked_at": datetime.now(timezone.utc).isoformat(),
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        
        (
            get_client()
            .table("vendors")
            .update(payload)
            .eq("id", vendor_id)
            .execute()
        )
        logger.info(f"Vendor {vendor_id}: Mapping aktualisiert auf Konto {account_nr}")
        return True
    except Exception as e:
        logger.error(f"Fehler beim Update Vendor-Mapping: {e}")
        return False


def list_vendors(limit: int = 50) -> List[VendorMemory]:
    """Listet alle gelernten Lieferanten, sortiert nach letzter Buchung."""
    try:
        result = (
            get_client()
            .table("vendors")
            .select("*")
            .order("last_booked_at", desc=True, nullsfirst=False)
            .limit(limit)
            .execute()
        )
        return [VendorMemory(**v) for v in result.data]
    except Exception as e:
        logger.error(f"Fehler beim Vendor-Listing: {e}")
        return []


# =========================================================
# ACCOUNT MAPPINGS (Bexio Kontenplan Cache)
# =========================================================

def sync_accounts(accounts: List[Dict[str, Any]]) -> int:
    """
    Upsert aller Konten aus Bexio in den lokalen Cache.
    accounts: Liste von Dicts im Bexio-Format.
    Returns: Anzahl gespeicherter Konten.
    """
    try:
        payloads = []
        for acc in accounts:
            payloads.append({
                "bexio_account_id": acc["id"],
                "account_nr": str(acc.get("account_no", "")),
                "account_name": acc.get("name", ""),
                "account_type": _account_type_label(acc.get("account_type")),
                "is_active": acc.get("is_active", True),
                "synced_at": datetime.now(timezone.utc).isoformat(),
            })
        
        if not payloads:
            return 0
        
        # Upsert via bexio_account_id (unique)
        result = (
            get_client()
            .table("account_mappings")
            .upsert(payloads, on_conflict="bexio_account_id")
            .execute()
        )
        count = len(result.data) if result.data else 0
        logger.info(f"{count} Konten synchronisiert")
        return count
    except Exception as e:
        logger.error(f"Fehler beim Account-Sync: {e}")
        return 0


def _account_type_label(type_id: Optional[int]) -> str:
    """Bexio Account-Type IDs zu Labels mappen."""
    mapping = {
        1: "asset",
        2: "liability",
        3: "equity",
        4: "income",
        5: "expense",
    }
    return mapping.get(type_id, "unknown")


def get_expense_accounts() -> List[Dict[str, Any]]:
    """Holt alle Aufwandskonten aus dem Cache."""
    try:
        result = (
            get_client()
            .table("account_mappings")
            .select("*")
            .eq("account_type", "expense")
            .eq("is_active", True)
            .order("account_nr")
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Fehler beim Laden Expense-Accounts: {e}")
        return []


def get_all_accounts() -> List[Dict[str, Any]]:
    """Holt alle aktiven Konten aus dem Cache."""
    try:
        result = (
            get_client()
            .table("account_mappings")
            .select("*")
            .eq("is_active", True)
            .order("account_nr")
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Fehler beim Laden Accounts: {e}")
        return []


def get_account_by_nr(account_nr: str) -> Optional[Dict[str, Any]]:
    """
    Loest eine Konto-Nummer (z.B. '2100') in das gecachte Account-Dict auf.
    Wird gebraucht um z.B. das Privatkonto-Konto-NR aus den Settings in eine
    Bexio-account-id aufzuloesen.
    """
    if not account_nr:
        return None
    try:
        result = (
            get_client()
            .table("account_mappings")
            .select("*")
            .eq("account_nr", str(account_nr))
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Fehler beim Account-Nr-Lookup '{account_nr}': {e}")
        return None


# =========================================================
# TAX MAPPINGS (MwSt-Codes Cache)
# =========================================================

def sync_taxes(taxes: List[Dict[str, Any]]) -> int:
    """Upsert aller MwSt-Codes aus Bexio."""
    try:
        payloads = []
        for tax in taxes:
            payloads.append({
                "bexio_tax_id": tax["id"],
                "tax_code": tax.get("code", ""),
                "tax_name": tax.get("name", ""),
                "tax_rate": float(tax.get("value", 0)),
                "tax_type": tax.get("type", ""),
                "is_active": tax.get("is_active", True),
                "synced_at": datetime.now(timezone.utc).isoformat(),
            })
        
        if not payloads:
            return 0
        
        result = (
            get_client()
            .table("tax_mappings")
            .upsert(payloads, on_conflict="bexio_tax_id")
            .execute()
        )
        count = len(result.data) if result.data else 0
        logger.info(f"{count} MwSt-Codes synchronisiert")
        return count
    except Exception as e:
        logger.error(f"Fehler beim Tax-Sync: {e}")
        return 0


def get_input_tax_codes() -> List[Dict[str, Any]]:
    """Vorsteuer-Codes (Eingangsrechnungen) holen."""
    try:
        result = (
            get_client()
            .table("tax_mappings")
            .select("*")
            .eq("is_active", True)
            .order("tax_rate", desc=True)
            .execute()
        )
        # Tax-Type kann "pre_tax" oder "sales_tax" sein, je nach Bexio-Version
        return result.data or []
    except Exception as e:
        logger.error(f"Fehler beim Laden Tax-Codes: {e}")
        return []


def find_tax_by_rate(rate: float) -> Optional[Dict[str, Any]]:
    """Findet den MwSt-Code fuer einen bestimmten Satz (z.B. 8.1)."""
    try:
        # Toleranz von 0.1% fuer Rundungsfehler
        result = (
            get_client()
            .table("tax_mappings")
            .select("*")
            .gte("tax_rate", rate - 0.05)
            .lte("tax_rate", rate + 0.05)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Fehler beim Tax-Lookup fuer Rate {rate}: {e}")
        return None


# =========================================================
# PENDING INVOICES
# =========================================================

def create_pending_invoice(
    source: str,
    file_path: str,
    original_filename: Optional[str] = None,
    file_size_bytes: Optional[int] = None,
    file_mime_type: Optional[str] = None,
    source_reference: Optional[str] = None,
) -> Optional[str]:
    """Erstellt einen neuen Pending-Invoice Eintrag. Returns: invoice_id oder None."""
    try:
        payload = {
            "source": source,
            "file_path": file_path,
            "original_filename": original_filename,
            "file_size_bytes": file_size_bytes,
            "file_mime_type": file_mime_type,
            "source_reference": source_reference,
            "status": "pending",
        }
        result = (
            get_client()
            .table("pending_invoices")
            .insert(payload)
            .execute()
        )
        if result.data:
            invoice_id = result.data[0]["id"]
            logger.info(f"Pending Invoice erstellt: {invoice_id}")
            return invoice_id
        return None
    except Exception as e:
        logger.error(f"Fehler beim Erstellen Pending Invoice: {e}")
        return None


def update_invoice_extraction(
    invoice_id: str,
    extracted_data: Dict[str, Any],
    vendor_name: Optional[str] = None,
    invoice_number: Optional[str] = None,
    invoice_date: Optional[str] = None,
    due_date: Optional[str] = None,
    total_amount: Optional[float] = None,
    vat_amount: Optional[float] = None,
    currency: Optional[str] = None,
    iban: Optional[str] = None,
    reference_number: Optional[str] = None,
    status: str = "extracted",
) -> bool:
    """Speichert extrahierte Daten von Gemini."""
    try:
        payload = {
            "extracted_data": extracted_data,
            "vendor_name": vendor_name,
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "due_date": due_date,
            "total_amount": total_amount,
            "vat_amount": vat_amount,
            "currency": currency,
            "iban": iban.replace(" ", "").upper() if iban else None,
            "reference_number": reference_number,
            "status": status,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        
        (
            get_client()
            .table("pending_invoices")
            .update(payload)
            .eq("id", invoice_id)
            .execute()
        )
        return True
    except Exception as e:
        logger.error(f"Fehler beim Update Invoice {invoice_id}: {e}")
        return False


def update_invoice_suggestion(
    invoice_id: str,
    suggested_vendor_id: Optional[str] = None,
    suggested_account_id: Optional[int] = None,
    suggested_tax_id: Optional[int] = None,
    confidence_score: Optional[float] = None,
    telegram_message_id: Optional[int] = None,
    status: str = "awaiting_approval",
) -> bool:
    """Speichert Buchungs-Vorschlag fuer den User."""
    try:
        payload = {
            "suggested_vendor_id": suggested_vendor_id,
            "suggested_account_id": suggested_account_id,
            "suggested_tax_id": suggested_tax_id,
            "confidence_score": confidence_score,
            "telegram_message_id": telegram_message_id,
            "status": status,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        
        (
            get_client()
            .table("pending_invoices")
            .update(payload)
            .eq("id", invoice_id)
            .execute()
        )
        return True
    except Exception as e:
        logger.error(f"Fehler beim Update Suggestion {invoice_id}: {e}")
        return False


def mark_invoice_booked(
    invoice_id: str,
    bexio_bill_id: int,
) -> bool:
    """Markiert Invoice als erfolgreich gebucht."""
    try:
        (
            get_client()
            .table("pending_invoices")
            .update({
                "status": "booked",
                "bexio_bill_id": bexio_bill_id,
                "bexio_booked_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", invoice_id)
            .execute()
        )
        return True
    except Exception as e:
        logger.error(f"Fehler beim Markieren als gebucht: {e}")
        return False


def mark_invoice_booked_private(
    invoice_id: str,
    bexio_manual_entry_id: str,
) -> bool:
    """
    Markiert Invoice als 'privat bezahlt' verbucht. Es wurde KEINE Bill in
    Bexio erstellt, sondern ein Manual-Journal-Entry direkt auf das
    Kontokorrent-Inhaber-Konto. Damit ist der Beleg buchhalterisch erledigt
    und faellt NICHT in den Bank-Reconciliation-Pool.
    """
    try:
        (
            get_client()
            .table("pending_invoices")
            .update({
                "status": "booked_private",
                "bexio_bill_id": str(bexio_manual_entry_id),
                "bexio_booked_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", invoice_id)
            .execute()
        )
        return True
    except Exception as e:
        logger.error(f"Fehler beim Markieren als 'privat bezahlt': {e}")
        return False


def mark_invoice_failed(invoice_id: str, error_message: str) -> bool:
    """Markiert Invoice als fehlgeschlagen."""
    try:
        (
            get_client()
            .table("pending_invoices")
            .update({
                "status": "failed",
                "error_message": error_message,
            })
            .eq("id", invoice_id)
            .execute()
        )
        return True
    except Exception as e:
        logger.error(f"Fehler beim Markieren als failed: {e}")
        return False


def get_invoice(invoice_id: str) -> Optional[Dict[str, Any]]:
    """Holt einen einzelnen Pending-Invoice Eintrag."""
    try:
        result = (
            get_client()
            .table("pending_invoices")
            .select("*")
            .eq("id", invoice_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Fehler beim Laden Invoice {invoice_id}: {e}")
        return None


def get_stats() -> Dict[str, int]:
    """Statistik fuer /stats Command."""
    try:
        result = (
            get_client()
            .table("pending_invoices")
            .select("status", count="exact")
            .execute()
        )
        all_invoices = result.data or []
        
        stats = {
            "total": len(all_invoices),
            "booked": sum(1 for i in all_invoices if i["status"] == "booked"),
            "pending": sum(1 for i in all_invoices if i["status"] in ["pending", "extracted", "awaiting_approval"]),
            "failed": sum(1 for i in all_invoices if i["status"] == "failed"),
            "rejected": sum(1 for i in all_invoices if i["status"] == "rejected"),
        }
        return stats
    except Exception as e:
        logger.error(f"Fehler beim Stats-Laden: {e}")
        return {"total": 0, "booked": 0, "pending": 0, "failed": 0, "rejected": 0}


# =========================================================
# INVOICE LOG (Audit Trail)
# =========================================================

def log_action(
    invoice_id: Optional[str],
    action: str,
    actor: str = "system",
    details: Optional[Dict[str, Any]] = None,
) -> bool:
    """Fuegt einen Eintrag ins Audit-Log ein."""
    try:
        payload = {
            "invoice_id": invoice_id,
            "action": action,
            "actor": actor,
            "details": details or {},
        }
        (
            get_client()
            .table("invoice_log")
            .insert(payload)
            .execute()
        )
        return True
    except Exception as e:
        # Log-Fehler nicht propagieren, sonst crasht alles
        logger.error(f"Fehler beim Audit-Log: {e}")
        return False
