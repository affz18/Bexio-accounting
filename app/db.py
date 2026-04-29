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
from app.models import VendorMemory, Tenant


logger = setup_logger(__name__)


# =========================================================
# MULTI-TENANT (Phase B1)
# =========================================================
# Default-Tenant fuer Code-Pfade die noch nicht tenant-aware sind.
# Alle DB-Funktionen akzeptieren tenant_id als Parameter mit diesem Default,
# sodass alter Code unveraendert weiter laeuft (gegen den 'visioskin'-Tenant)
# und neuer Multi-Tenant-Code explizit eine andere ID uebergeben kann.
DEFAULT_TENANT_ID = "visioskin"


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

def is_user_authorized(
    telegram_chat_id: int,
    tenant_id: Optional[str] = None,
) -> bool:
    """
    Prueft ob ein User den Bot nutzen darf (via DB).
    Ohne tenant_id: prueft ueber alle Tenants (fuer Bot-Auth ohne Kontext).
    """
    try:
        query = (
            get_client()
            .table("authorized_users")
            .select("id")
            .eq("telegram_chat_id", telegram_chat_id)
        )
        if tenant_id:
            query = query.eq("tenant_id", tenant_id)
        result = query.limit(1).execute()
        return len(result.data) > 0
    except Exception as e:
        logger.error(f"Fehler beim Auth-Check: {e}")
        return False


def get_user_settings(
    telegram_chat_id: int,
    tenant_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Holt die User-Settings (kann_auto_book etc.)."""
    try:
        query = (
            get_client()
            .table("authorized_users")
            .select("*")
            .eq("telegram_chat_id", telegram_chat_id)
        )
        if tenant_id:
            query = query.eq("tenant_id", tenant_id)
        result = query.limit(1).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Fehler beim Laden User-Settings: {e}")
        return None


# =========================================================
# VENDORS (Lieferanten-Memory)
# =========================================================

def find_vendor_by_name(
    name: str,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> Optional[VendorMemory]:
    """Sucht einen Lieferanten ueber den normalisierten Namen."""
    normalized = normalize_vendor_name(name)
    if not normalized:
        return None

    try:
        result = (
            get_client()
            .table("vendors")
            .select("*")
            .eq("tenant_id", tenant_id)
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


def find_vendor_by_bexio_contact_id(
    bexio_contact_id: int,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> Optional[VendorMemory]:
    """Sucht Vendor ueber die Bexio-Contact-ID (eindeutige Verknuepfung)."""
    if not bexio_contact_id:
        return None
    try:
        result = (
            get_client()
            .table("vendors")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("bexio_contact_id", bexio_contact_id)
            .limit(1)
            .execute()
        )
        if result.data:
            return VendorMemory(**result.data[0])
        return None
    except Exception as e:
        logger.error(f"Fehler beim Vendor-Lookup bexio_contact_id={bexio_contact_id}: {e}")
        return None


def find_vendor_by_iban(
    iban: str,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> Optional[VendorMemory]:
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
            .eq("tenant_id", tenant_id)
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
    tenant_id: str = DEFAULT_TENANT_ID,
) -> Optional[VendorMemory]:
    """Legt einen neuen Lieferanten in der Memory an."""
    try:
        payload = {
            "tenant_id": tenant_id,
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


def upsert_vendor_from_history(
    bexio_contact_id: int,
    name: str,
    default_account_id: int,
    default_account_nr: Optional[str] = None,
    default_tax_id: Optional[int] = None,
    default_tax_rate: Optional[float] = None,
    booking_count: int = 1,
    last_booked_at: Optional[str] = None,
    iban: Optional[str] = None,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> Optional[str]:
    """
    Upsert eines Vendors basierend auf Bexio-History.
    Returns: "created" | "updated" | "skipped" | None bei Fehler.

    Conflict-Resolution:
    - Existiert vendor mit diesem bexio_contact_id ODER gleichem normalisierten
      Name: nur ueberschreiben wenn Bexio-History eine hoehere Confidence
      ergibt als die bisher gespeicherte (manuelle Korrekturen bleiben erhalten).
    - bexio_contact_id, name und last_booked_at werden immer aktualisiert.
    """
    bexio_confidence = min(0.50 + (booking_count * 0.05), 0.95)

    existing = (
        find_vendor_by_bexio_contact_id(bexio_contact_id, tenant_id=tenant_id)
        or find_vendor_by_name(name, tenant_id=tenant_id)
    )

    base_payload: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "name": name,
        "normalized_name": normalize_vendor_name(name),
        "bexio_contact_id": bexio_contact_id,
    }
    if iban:
        base_payload["iban"] = iban.replace(" ", "").upper()
    if last_booked_at:
        # YYYY-MM-DD oder ISO-String akzeptieren
        if "T" in last_booked_at:
            base_payload["last_booked_at"] = last_booked_at
        else:
            base_payload["last_booked_at"] = f"{last_booked_at}T00:00:00+00:00"

    mapping_payload: Dict[str, Any] = {
        "default_account_id": default_account_id,
        "default_account_nr": default_account_nr,
        "default_tax_id": default_tax_id,
        "default_tax_rate": default_tax_rate,
        "booking_count": booking_count,
        "confidence_score": bexio_confidence,
    }

    try:
        if existing:
            existing_conf = existing.confidence_score or 0.0
            payload = {**base_payload}
            if bexio_confidence > existing_conf:
                payload.update(mapping_payload)
                action = "updated"
            else:
                action = "skipped"
            payload = {k: v for k, v in payload.items() if v is not None}
            (
                get_client()
                .table("vendors")
                .update(payload)
                .eq("id", existing.id)
                .execute()
            )
            return action

        payload = {**base_payload, **mapping_payload}
        payload = {k: v for k, v in payload.items() if v is not None}
        (
            get_client()
            .table("vendors")
            .insert(payload)
            .execute()
        )
        return "created"
    except Exception as e:
        logger.error(f"Fehler beim History-Upsert Vendor '{name}': {e}")
        return None


def list_vendors(
    limit: int = 50,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> List[VendorMemory]:
    """Listet alle gelernten Lieferanten, sortiert nach letzter Buchung."""
    try:
        result = (
            get_client()
            .table("vendors")
            .select("*")
            .eq("tenant_id", tenant_id)
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

def sync_accounts(
    accounts: List[Dict[str, Any]],
    tenant_id: str = DEFAULT_TENANT_ID,
) -> int:
    """
    Upsert aller Konten aus Bexio in den lokalen Cache.
    accounts: Liste von Dicts im Bexio-Format.
    Returns: Anzahl gespeicherter Konten.
    """
    try:
        payloads = []
        for acc in accounts:
            payloads.append({
                "tenant_id": tenant_id,
                "bexio_account_id": acc["id"],
                "account_nr": str(acc.get("account_no", "")),
                "account_name": acc.get("name", ""),
                "account_type": _account_type_label(acc.get("account_type")),
                "is_active": acc.get("is_active", True),
                "synced_at": datetime.now(timezone.utc).isoformat(),
            })

        if not payloads:
            return 0

        # Upsert via (tenant_id, bexio_account_id) - unique pro Tenant
        result = (
            get_client()
            .table("account_mappings")
            .upsert(payloads, on_conflict="tenant_id,bexio_account_id")
            .execute()
        )
        count = len(result.data) if result.data else 0
        logger.info(f"{count} Konten synchronisiert (tenant={tenant_id})")
        return count
    except Exception as e:
        logger.error(f"Fehler beim Account-Sync: {e}")
        return 0


def _account_type_label(type_id: Optional[int]) -> str:
    """
    Bexio Account-Type IDs zu Labels mappen.
    Canonical Bexio mapping (nicht was man intuitiv erwartet!):
      1 = EARNINGS         -> Ertrag (income)
      2 = EXPENDITURES     -> Aufwand (expense)
      3 = ACTIVE_ACCOUNTS  -> Aktiven (asset)
      4 = PASSIVE_ACCOUNTS -> Passiven (liability, inkl. Eigenkapital)
      5 = COMPLETE_ACCOUNTS-> Abschlusskonten 9xxx (closing)
    """
    mapping = {
        1: "income",
        2: "expense",
        3: "asset",
        4: "liability",
        5: "closing",
    }
    return mapping.get(type_id, "unknown")


def get_expense_accounts(
    tenant_id: str = DEFAULT_TENANT_ID,
) -> List[Dict[str, Any]]:
    """Holt alle Aufwandskonten aus dem Cache."""
    try:
        result = (
            get_client()
            .table("account_mappings")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("account_type", "expense")
            .eq("is_active", True)
            .order("account_nr")
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Fehler beim Laden Expense-Accounts: {e}")
        return []


def get_all_accounts(
    tenant_id: str = DEFAULT_TENANT_ID,
) -> List[Dict[str, Any]]:
    """Holt alle aktiven Konten aus dem Cache."""
    try:
        result = (
            get_client()
            .table("account_mappings")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("is_active", True)
            .order("account_nr")
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Fehler beim Laden Accounts: {e}")
        return []


# =========================================================
# TAX MAPPINGS (MwSt-Codes Cache)
# =========================================================

def sync_taxes(
    taxes: List[Dict[str, Any]],
    tenant_id: str = DEFAULT_TENANT_ID,
) -> int:
    """Upsert aller MwSt-Codes aus Bexio."""
    try:
        payloads = []
        for tax in taxes:
            payloads.append({
                "tenant_id": tenant_id,
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
            .upsert(payloads, on_conflict="tenant_id,bexio_tax_id")
            .execute()
        )
        count = len(result.data) if result.data else 0
        logger.info(f"{count} MwSt-Codes synchronisiert (tenant={tenant_id})")
        return count
    except Exception as e:
        logger.error(f"Fehler beim Tax-Sync: {e}")
        return 0


def get_input_tax_codes(
    tenant_id: str = DEFAULT_TENANT_ID,
) -> List[Dict[str, Any]]:
    """
    Vorsteuer-Codes (Eingangsrechnungen) holen.
    Bexio unterscheidet pre_tax (Vorsteuer, Kreditoren) und sales_tax
    (Umsatzsteuer, Debitoren). Fuer Eingangsrechnungen brauchen wir nur
    pre_tax - sonst wirft Bexio purchase.validation.tax_incorrect.
    """
    try:
        result = (
            get_client()
            .table("tax_mappings")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("is_active", True)
            .eq("tax_type", "pre_tax")
            .order("tax_rate", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Fehler beim Laden Tax-Codes: {e}")
        return []


def find_tax_by_rate(rate: float, tax_type: str = "pre_tax") -> Optional[Dict[str, Any]]:
    """
    Findet den MwSt-Code fuer einen bestimmten Satz (z.B. 8.1).
    Bexio hat pro Satz zwei IDs (pre_tax fuer Eingang, sales_tax fuer Ausgang).
    Default pre_tax weil unser Hauptpfad Kreditorenbuchungen sind.
    """
    try:
        # Toleranz von 0.1% fuer Rundungsfehler
        result = (
            get_client()
            .table("tax_mappings")
            .select("*")
            .gte("tax_rate", rate - 0.05)
            .lte("tax_rate", rate + 0.05)
            .eq("is_active", True)
            .eq("tax_type", tax_type)
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
    tenant_id: str = DEFAULT_TENANT_ID,
) -> Optional[str]:
    """Erstellt einen neuen Pending-Invoice Eintrag. Returns: invoice_id oder None."""
    try:
        payload = {
            "tenant_id": tenant_id,
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


def get_invoice(
    invoice_id: str,
    tenant_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Holt einen einzelnen Pending-Invoice Eintrag.
    Mit tenant_id: filtert zusaetzlich (defense-in-depth gegen ID-Kollisionen
    wenn verschiedene Tenants Invoices haben). Ohne: nur via id-PK.
    """
    try:
        query = (
            get_client()
            .table("pending_invoices")
            .select("*")
            .eq("id", invoice_id)
        )
        if tenant_id:
            query = query.eq("tenant_id", tenant_id)
        result = query.limit(1).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Fehler beim Laden Invoice {invoice_id}: {e}")
        return None


def get_stats(
    tenant_id: str = DEFAULT_TENANT_ID,
) -> Dict[str, int]:
    """Statistik fuer /stats Command."""
    try:
        result = (
            get_client()
            .table("pending_invoices")
            .select("status", count="exact")
            .eq("tenant_id", tenant_id)
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
    tenant_id: str = DEFAULT_TENANT_ID,
) -> bool:
    """Fuegt einen Eintrag ins Audit-Log ein."""
    try:
        payload = {
            "tenant_id": tenant_id,
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


# =========================================================
# IMAP PROCESSED EMAILS (Idempotenz fuer Inbox-Scan)
# =========================================================

def is_email_uid_processed(
    uid: str,
    folder: str = "INBOX",
    account: str = "",
    tenant_id: str = DEFAULT_TENANT_ID,
) -> bool:
    """True, wenn diese (tenant, account, folder, uid)-Kombi bereits verarbeitet wurde."""
    try:
        result = (
            get_client()
            .table("processed_emails")
            .select("uid")
            .eq("tenant_id", tenant_id)
            .eq("account", account)
            .eq("folder", folder)
            .eq("uid", uid)
            .limit(1)
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        logger.error(f"Fehler beim UID-Check {uid}: {e}")
        # Im Zweifel als unverarbeitet behandeln - lieber doppelt schicken
        # als verlieren, der User kann dann reject klicken.
        return False


def mark_email_uid_processed(
    uid: str,
    folder: str,
    account: str,
    status: str,
    invoice_id: Optional[str] = None,
    subject: Optional[str] = None,
    from_address: Optional[str] = None,
    error: Optional[str] = None,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> bool:
    """
    Markiert eine IMAP-Mail als verarbeitet.
    status: 'filtered' | 'processed' | 'failed' | 'no_attachment'
    """
    try:
        payload = {
            "tenant_id": tenant_id,
            "uid": uid,
            "folder": folder,
            "account": account,
            "status": status,
            "invoice_id": invoice_id,
            "subject": subject,
            "from_address": from_address,
            "error": error,
        }
        (
            get_client()
            .table("processed_emails")
            .upsert(payload, on_conflict="tenant_id,account,folder,uid")
            .execute()
        )
        return True
    except Exception as e:
        logger.error(f"Fehler beim UID-Mark {uid}: {e}")
        return False


# =========================================================
# BANK-RECONCILIATION (Phase 4)
# =========================================================

def get_open_invoices_for_matching(
    tenant_id: str = DEFAULT_TENANT_ID,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """
    Liefert Pending-Invoices die als noch nicht bezahlt gelten und damit
    Match-Kandidaten fuer Bank-Bewegungen sind. Status 'booked' (in Bexio
    gebucht aber noch nicht abgeglichen) und 'extracted'/'awaiting_approval'
    sind alle relevant - selbst wenn noch nicht in Bexio gebucht, kann der
    User aus dem Match-Vorschlag implizit buchen lassen.
    """
    try:
        result = (
            get_client()
            .table("pending_invoices")
            .select("id, vendor_name, total_amount, iban, reference_number, "
                    "invoice_date, due_date, status, bexio_bill_id")
            .in_("status", ["extracted", "awaiting_approval", "booked"])
            .order("invoice_date", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Fehler beim Laden offener Invoices: {e}")
        return []


def upsert_bank_transaction(tx_payload: Dict[str, Any]) -> Optional[str]:
    """
    Speichert eine Bank-Transaktion. Bei Konflikt auf
    (tenant_id, bank_account_iban, transaction_id) wird nicht ueberschrieben -
    die TX wurde schon importiert.

    Returns: bank_transactions.id (uuid) bei Insert, oder die bestehende ID
             bei Konflikt, oder None bei Fehler.
    """
    try:
        result = (
            get_client()
            .table("bank_transactions")
            .upsert(
                tx_payload,
                on_conflict="tenant_id,bank_account_iban,transaction_id",
                ignore_duplicates=False,
            )
            .execute()
        )
        if result.data:
            return result.data[0].get("id")
        return None
    except Exception as e:
        logger.error(f"Fehler beim Bank-TX-Upsert: {e}")
        return None


def insert_payment_match(match_payload: Dict[str, Any]) -> Optional[str]:
    """Speichert einen MatchCandidate als payment_matches-Zeile."""
    try:
        result = (
            get_client()
            .table("payment_matches")
            .insert(match_payload)
            .execute()
        )
        if result.data:
            return result.data[0].get("id")
        return None
    except Exception as e:
        logger.error(f"Fehler beim Payment-Match-Insert: {e}")
        return None


def get_pending_match_proposals(
    tenant_id: str = DEFAULT_TENANT_ID,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Liefert alle vom System vorgeschlagenen, noch nicht bestaetigten Matches."""
    try:
        result = (
            get_client()
            .table("payment_matches")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("status", "proposed")
            .order("confidence", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Fehler beim Laden Match-Proposals: {e}")
        return []


def update_payment_match_status(
    match_id: str,
    status: str,
    bexio_payment_id: Optional[str] = None,
    error_message: Optional[str] = None,
) -> bool:
    """Updated den Status eines Payment-Match (confirmed/booked/rejected/failed)."""
    payload: Dict[str, Any] = {"status": status}
    now_iso = datetime.now(timezone.utc).isoformat()
    if status == "confirmed":
        payload["confirmed_at"] = now_iso
    elif status == "booked":
        payload["booked_at"] = now_iso
        if bexio_payment_id:
            payload["bexio_payment_id"] = bexio_payment_id
    if error_message:
        payload["error_message"] = error_message[:500]
    try:
        (
            get_client()
            .table("payment_matches")
            .update(payload)
            .eq("id", match_id)
            .execute()
        )
        return True
    except Exception as e:
        logger.error(f"Fehler beim Payment-Match-Update {match_id}: {e}")
        return False


def update_bank_transaction_match_status(
    bank_transaction_id: str,
    match_status: str,
) -> bool:
    """Updated den match_status einer Bank-Transaktion."""
    try:
        payload: Dict[str, Any] = {"match_status": match_status}
        if match_status == "matched":
            payload["matched_at"] = datetime.now(timezone.utc).isoformat()
        (
            get_client()
            .table("bank_transactions")
            .update(payload)
            .eq("id", bank_transaction_id)
            .execute()
        )
        return True
    except Exception as e:
        logger.error(f"Fehler beim Bank-TX-Status-Update {bank_transaction_id}: {e}")
        return False


def get_bank_transaction(bank_transaction_id: str) -> Optional[Dict[str, Any]]:
    """Holt eine Bank-Transaktion fuer den Match-Display."""
    try:
        result = (
            get_client()
            .table("bank_transactions")
            .select("*")
            .eq("id", bank_transaction_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Fehler beim Laden Bank-TX {bank_transaction_id}: {e}")
        return None


def get_payment_match(match_id: str) -> Optional[Dict[str, Any]]:
    """Holt einen Match-Vorschlag mit allen Details."""
    try:
        result = (
            get_client()
            .table("payment_matches")
            .select("*")
            .eq("id", match_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Fehler beim Laden Payment-Match {match_id}: {e}")
        return None


# =========================================================
# TENANTS (Multi-Tenant Foundation - Phase B1)
# =========================================================
#
# Diese Helpers lesen die tenants-Tabelle. In Phase B1 hat das System nur
# den Default-Tenant 'visioskin'. Die get-Funktionen sind cached weil
# Tenant-Daten sich quasi nie aendern.
# DEFAULT_TENANT_ID ist oben in der Datei definiert (wegen Reihenfolge).

_tenant_cache: Dict[str, Tenant] = {}


def get_tenant(tenant_id: str = DEFAULT_TENANT_ID) -> Optional[Tenant]:
    """
    Holt einen Tenant aus der DB. Cached pro Prozess-Lifetime.
    Returns None wenn der Tenant nicht existiert oder inaktiv ist.
    """
    if tenant_id in _tenant_cache:
        return _tenant_cache[tenant_id]
    try:
        result = (
            get_client()
            .table("tenants")
            .select("*")
            .eq("id", tenant_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        tenant = Tenant(**result.data[0])
        _tenant_cache[tenant_id] = tenant
        return tenant
    except Exception as e:
        logger.error(f"Fehler beim Laden Tenant {tenant_id}: {e}")
        return None


def list_tenants(only_active: bool = True) -> List[Tenant]:
    """Listet alle Tenants. Nuetzlich fuer Background-Tasks (z.B. IMAP-Scan
    fuer alle aktiven Tenants)."""
    try:
        query = get_client().table("tenants").select("*")
        if only_active:
            query = query.eq("is_active", True)
        result = query.order("id").execute()
        return [Tenant(**t) for t in (result.data or [])]
    except Exception as e:
        logger.error(f"Fehler beim Listen Tenants: {e}")
        return []


def resolve_tenant_for_chat(telegram_chat_id: int) -> Optional[str]:
    """
    Findet den Tenant zu einer Telegram-Chat-ID via authorized_users.
    Falls der Chat in mehreren Tenants ist (selten), nimmt den ersten -
    spaeter koennten wir hier explizite Auswahl machen.

    Returns: tenant_id oder None wenn unauthorized.
    """
    try:
        result = (
            get_client()
            .table("authorized_users")
            .select("tenant_id")
            .eq("telegram_chat_id", telegram_chat_id)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0].get("tenant_id") or DEFAULT_TENANT_ID
        return None
    except Exception as e:
        logger.error(f"Tenant-Resolution fuer Chat {telegram_chat_id} fehlgeschlagen: {e}")
        return None


def clear_tenant_cache() -> None:
    """Leert den Tenant-Cache. Aufrufen wenn Tenant-Daten geaendert wurden."""
    global _tenant_cache
    _tenant_cache = {}
