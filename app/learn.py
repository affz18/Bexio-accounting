"""
Bexio-History-Learning.

Liest existierende Supplier-Bills aus Bexio und baut daraus das
Vendor->Konto-Memory in Supabase auf, damit der Bot ab Tag 1 weiss
wie der User typischerweise verbucht.

Workflow:
1. Alle Contacts cachen (supplier_id -> name)
2. Alle Bills paginiert listen (v4, condensed - keine line_items)
3. Pro Bill Detail laden (line_items mit booking_account_id + tax_id)
4. Pro Vendor: meist-genutztes (account_id, tax_id) aggregieren
5. In vendors-Tabelle upserten (existierende Memorys mit hoeherer
   Confidence bleiben erhalten)
"""
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Dict, List, Optional

from app import bexio as bexio_module
from app import db
from app.utils import setup_logger


logger = setup_logger(__name__)


ProgressFn = Callable[[str], Awaitable[None]]


class LearnStats:
    def __init__(self) -> None:
        self.contacts_loaded = 0
        self.bills_listed = 0
        self.bills_processed = 0
        self.bills_skipped = 0
        self.vendors_created = 0
        self.vendors_updated = 0
        self.vendors_skipped = 0


async def _noop_progress(_: str) -> None:
    return None


async def learn_from_bexio_history(
    months_back: int = 12,
    max_bills: int = 1000,
    progress: Optional[ProgressFn] = None,
) -> LearnStats:
    """
    Liest die letzten `months_back` Monate Supplier-Bills aus Bexio
    und baut das Vendor-Memory auf. Hartes Cap bei `max_bills` (Schutz
    vor sehr grossen Mandaten).
    """
    stats = LearnStats()
    progress = progress or _noop_progress

    # Lookups aus dem lokalen Cache
    accounts = db.get_all_accounts()
    account_nr_by_id = {a["bexio_account_id"]: a.get("account_nr") for a in accounts}

    taxes = db.get_input_tax_codes()
    tax_rate_by_id = {t["bexio_tax_id"]: t.get("tax_rate") for t in taxes}

    if not account_nr_by_id:
        raise RuntimeError(
            "Kein Konten-Cache vorhanden. Bitte erst /sync ausfuehren."
        )

    # 1. Contacts cachen
    await progress("Lade Bexio-Kontakte...")
    contacts_by_id = await _load_contacts_cache()
    stats.contacts_loaded = len(contacts_by_id)
    logger.info(f"Geladen: {stats.contacts_loaded} Kontakte")

    # 2. Bill-IDs listen
    bill_date_start = (
        datetime.now(timezone.utc) - timedelta(days=months_back * 31)
    ).date().isoformat()

    bill_ids = await _list_all_bill_ids(
        bill_date_start=bill_date_start,
        max_bills=max_bills,
        stats=stats,
        progress=progress,
    )

    if not bill_ids:
        logger.info("Keine Bills gefunden")
        return stats

    # 3. Per-Bill Details + Aggregat aufbauen
    vendor_account_counts: Dict[int, Counter] = defaultdict(Counter)
    vendor_last_bill_date: Dict[int, str] = {}

    total = len(bill_ids)
    for i, bill_id in enumerate(bill_ids, start=1):
        if i % 25 == 0 or i == total:
            await progress(f"Verarbeite Bill {i}/{total}...")

        try:
            detail = await bexio_module.bexio.get_supplier_bill(bill_id)
        except Exception as e:
            logger.warning(f"Bill {bill_id} nicht ladbar: {e}")
            stats.bills_skipped += 1
            continue

        if not detail or detail.get("status") == "DRAFT":
            stats.bills_skipped += 1
            continue

        supplier_id = detail.get("supplier_id")
        primary = _pick_primary_line_item(detail.get("line_items") or [])
        if not supplier_id or not primary:
            stats.bills_skipped += 1
            continue

        account_id = primary.get("booking_account_id")
        if not account_id:
            stats.bills_skipped += 1
            continue

        tax_id = primary.get("tax_id")
        vendor_account_counts[supplier_id][(account_id, tax_id)] += 1

        bill_date = detail.get("bill_date")
        if bill_date:
            current_last = vendor_last_bill_date.get(supplier_id)
            if not current_last or bill_date > current_last:
                vendor_last_bill_date[supplier_id] = bill_date

        stats.bills_processed += 1

    # 4. Vendors upserten
    vendor_count = len(vendor_account_counts)
    await progress(f"Speichere {vendor_count} Lieferanten...")

    for supplier_id, counter in vendor_account_counts.items():
        if not counter:
            continue

        (best_account_id, best_tax_id), count = counter.most_common(1)[0]

        contact = contacts_by_id.get(supplier_id)
        if not contact:
            logger.warning(f"Kein Contact fuer supplier_id={supplier_id}, skip")
            stats.vendors_skipped += 1
            continue

        vendor_name = _build_contact_display_name(contact)
        if not vendor_name:
            stats.vendors_skipped += 1
            continue

        result = db.upsert_vendor_from_history(
            bexio_contact_id=supplier_id,
            name=vendor_name,
            default_account_id=best_account_id,
            default_account_nr=account_nr_by_id.get(best_account_id),
            default_tax_id=best_tax_id,
            default_tax_rate=tax_rate_by_id.get(best_tax_id) if best_tax_id else None,
            booking_count=count,
            last_booked_at=vendor_last_bill_date.get(supplier_id),
        )
        if result == "created":
            stats.vendors_created += 1
        elif result == "updated":
            stats.vendors_updated += 1
        else:
            stats.vendors_skipped += 1

    logger.info(
        f"Lern-Run fertig: {stats.bills_processed} Bills verarbeitet, "
        f"{stats.vendors_created} neu, {stats.vendors_updated} aktualisiert"
    )
    return stats


# =========================================================
# Helpers
# =========================================================

async def _load_contacts_cache() -> Dict[int, Dict]:
    """Laedt alle Bexio-Contacts in ein Dict by id (paginiert)."""
    contacts: Dict[int, Dict] = {}
    offset = 0
    page_size = 2000
    while True:
        page = await bexio_module.bexio.list_contacts_page(
            offset=offset, limit=page_size
        )
        if not page:
            break
        for contact in page:
            cid = contact.get("id")
            if cid:
                contacts[cid] = contact
        if len(page) < page_size:
            break
        offset += page_size
    return contacts


async def _list_all_bill_ids(
    bill_date_start: str,
    max_bills: int,
    stats: LearnStats,
    progress: ProgressFn,
) -> List:
    """Listet alle Bill-IDs (paginiert, neueste zuerst)."""
    bill_ids: List = []
    page = 1
    page_size = 500
    while len(bill_ids) < max_bills:
        await progress(f"Lade Bills (Seite {page})...")
        try:
            response = await bexio_module.bexio.list_supplier_bills_page(
                page=page,
                limit=page_size,
                bill_date_start=bill_date_start,
            )
        except Exception as e:
            logger.error(f"Fehler beim Bill-Listing Seite {page}: {e}")
            break

        items = response.get("data") or []
        if not items:
            break

        for item in items:
            bid = item.get("id")
            if bid is None:
                continue
            bill_ids.append(bid)
            if len(bill_ids) >= max_bills:
                break

        stats.bills_listed = len(bill_ids)

        paging = response.get("paging") or {}
        page_count = paging.get("page_count")
        if page_count and page >= page_count:
            break
        if len(items) < page_size:
            break
        page += 1

    return bill_ids


def _pick_primary_line_item(line_items: List[Dict]) -> Optional[Dict]:
    """Line-Item mit groesstem Betrag, sofern booking_account_id gesetzt."""
    valid = [li for li in line_items if li.get("booking_account_id")]
    if not valid:
        return None
    return max(valid, key=lambda li: float(li.get("amount") or 0))


def _build_contact_display_name(contact: Dict) -> str:
    """
    Baut den Display-Namen je nach contact_type_id:
    - 1 = Firma   -> name_1 (+ optional name_2 als Zusatz)
    - 2 = Person  -> "Vorname Nachname" = "name_2 name_1"
    """
    type_id = contact.get("contact_type_id")
    name_1 = (contact.get("name_1") or "").strip()
    name_2 = (contact.get("name_2") or "").strip()

    if type_id == 2 and name_2 and name_1:
        return f"{name_2} {name_1}"
    if name_1 and name_2:
        return f"{name_1} {name_2}"
    return name_1 or name_2


# =========================================================
# Telegram-Progress-Throttle
# =========================================================

class ProgressThrottle:
    """
    Telegram erlaubt nur ~1 Edit/sec; wir drosseln Status-Updates auf
    max alle `min_interval_s` Sekunden und unterdruecken Duplikate.
    """

    def __init__(self, edit_callback: Callable[[str], Awaitable[None]], min_interval_s: float = 2.0):
        self._edit = edit_callback
        self._min_interval = min_interval_s
        self._last_text = ""
        self._last_ts = 0.0

    async def __call__(self, text: str) -> None:
        if text == self._last_text:
            return
        now = time.monotonic()
        if now - self._last_ts < self._min_interval:
            return
        self._last_text = text
        self._last_ts = now
        try:
            await self._edit(text)
        except Exception as e:
            logger.debug(f"Progress-Edit fehlgeschlagen (ignored): {e}")
