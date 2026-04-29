"""
MWST-Modul (Phase A) - Vorsteuer-Aggregation aus Bexio.

Erstellt einen quartalsweisen Vorsteuer-Bericht aus den Lieferantenrechnungen
in Bexio. Mappt auf die ESTV-Form-0050-Logik (Ziffern 400 / 405) so weit wie
moeglich, ohne direkte ESTV-Submission.

Workflow:
1. User gibt Quartal an (z.B. "2026Q3" oder "2026Q3").
2. Bot laedt alle Lieferantenrechnungen mit bill_date in dem Quartal.
3. Pro Bill: line_items mit tax_id auswerten, in Aggregator giessen.
4. Pro MwSt-Satz: Brutto, Netto, MwSt summieren.
5. Pro Konto-Klasse (4xxx vs 5-8xxx) trennen fuer ESTV-Ziffer 400 vs 405.
6. Anomalien sammeln (Belege ohne Tax-Code, unbekannte Tax-IDs).

Bewusst NICHT in V1:
- Umsatzsteuer (Sales-Invoices) - separater Pfad in Phase B
- Vorsteuerkuerzung (gemischte Taetigkeit) - manuelle Treuhand-Arbeit
- Direkt-Submission an ESTV - braucht eID/AGOV, nicht offen

Wichtig: dieser Bericht ist ein **Sanity-Check** vor der Bexio-eigenen
MwSt-Abrechnung, kein Ersatz. Treuhand validiert vor Abgabe.
"""
import re
from collections import defaultdict
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from app.utils import setup_logger


logger = setup_logger(__name__)


# =========================================================
# QUARTAL-HELPER
# =========================================================

# Akzeptiert: "2026Q3", "Q3 2026", "2026-Q3", "2026/3", "3/2026"
_QUARTER_PATTERNS = [
    re.compile(r"^\s*(?P<year>\d{4})\s*[-/]?\s*[Qq]?(?P<q>[1-4])\s*$"),
    re.compile(r"^\s*[Qq]?(?P<q>[1-4])\s*[-/]?\s*(?P<year>\d{4})\s*$"),
]


def parse_quarter_string(s: str) -> Tuple[int, int]:
    """
    Parst diverse Quartal-Schreibweisen in (year, quarter).

    Raises:
        ValueError: bei nicht-parsebarem Input.
    """
    if not s:
        raise ValueError("Leerer Quartal-Input")
    for pat in _QUARTER_PATTERNS:
        m = pat.match(s.strip())
        if m:
            year = int(m.group("year"))
            q = int(m.group("q"))
            if 2000 <= year <= 2100 and 1 <= q <= 4:
                return year, q
    raise ValueError(
        f"Quartal nicht erkannt: {s!r}. "
        f"Beispiele: '2026Q3', 'Q3 2026', '2026/3'"
    )


def quarter_date_range(year: int, quarter: int) -> Tuple[date, date]:
    """Liefert (start_date, end_date) inkl. Endtag fuer ein Quartal."""
    if quarter not in (1, 2, 3, 4):
        raise ValueError(f"Quarter muss 1-4 sein, war {quarter}")
    from datetime import timedelta
    start_month = 3 * (quarter - 1) + 1
    end_month = start_month + 2
    start = date(year, start_month, 1)
    if end_month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, end_month + 1, 1) - timedelta(days=1)
    return start, end


def current_quarter() -> Tuple[int, int]:
    """Liefert (year, quarter) fuer das aktuelle Quartal."""
    today = datetime.utcnow().date()
    return today.year, (today.month - 1) // 3 + 1


def previous_quarter() -> Tuple[int, int]:
    """Liefert (year, quarter) fuer das vorhergehende Quartal."""
    y, q = current_quarter()
    if q == 1:
        return y - 1, 4
    return y, q - 1


# =========================================================
# REPORT-AGGREGATION
# =========================================================

# Konto-Klassen-Mapping fuer ESTV-Ziffer 400 vs 405:
# - 4xxx: Material, Waren, Dienstleistungs-Aufwand -> Ziffer 400
# - 5xxx-8xxx: Personal, Betrieb, Investitionen, ausserord. -> Ziffer 405
# Konten ausserhalb 4-8 (z.B. 1xxx Aktiv) sollten in Lieferanten-Rechnungen
# nicht als Aufwand gebucht werden. Fallen in 'unklassifiziert'.

def _account_class(account_nr: Optional[str]) -> str:
    """Mapped Konto-Nr-Praefix in ESTV-Klasse."""
    if not account_nr:
        return "unclassified"
    first = str(account_nr)[0]
    if first == "4":
        return "material"  # Ziffer 400
    if first in ("5", "6", "7", "8"):
        return "investitionen"  # Ziffer 405
    return "unclassified"


class VatLine:
    """Eine Zeile im Bericht: pro (Tax-Code, Konto-Klasse)."""

    def __init__(
        self,
        tax_code: str,
        tax_name: str,
        tax_rate: float,
        tax_type: str,
        account_class: str,
    ) -> None:
        self.tax_code = tax_code
        self.tax_name = tax_name
        self.tax_rate = tax_rate
        self.tax_type = tax_type
        self.account_class = account_class
        self.line_count = 0
        self.total_gross = 0.0
        self.total_net = 0.0
        self.total_vat = 0.0

    def add(self, gross: float, net: float, vat: float) -> None:
        self.line_count += 1
        self.total_gross += gross
        self.total_net += net
        self.total_vat += vat

    def to_dict(self) -> Dict:
        return {
            "tax_code": self.tax_code,
            "tax_name": self.tax_name,
            "tax_rate": round(self.tax_rate, 2),
            "tax_type": self.tax_type,
            "account_class": self.account_class,
            "line_count": self.line_count,
            "total_gross": round(self.total_gross, 2),
            "total_net": round(self.total_net, 2),
            "total_vat": round(self.total_vat, 2),
        }


class VatReport:
    """Aggregat ueber ein Quartal."""

    def __init__(self, year: int, quarter: int, start: date, end: date) -> None:
        self.year = year
        self.quarter = quarter
        self.period_start = start
        self.period_end = end
        self.quarter_label = f"{year}Q{quarter}"
        self.lines: Dict[Tuple[str, str], VatLine] = {}
        self.bills_processed = 0
        self.bills_skipped = 0
        self.warnings: List[str] = []

    def line_for(
        self,
        tax_code: str,
        tax_name: str,
        tax_rate: float,
        tax_type: str,
        account_class: str,
    ) -> VatLine:
        key = (tax_code, account_class)
        line = self.lines.get(key)
        if line is None:
            line = VatLine(tax_code, tax_name, tax_rate, tax_type, account_class)
            self.lines[key] = line
        return line

    @property
    def total_gross(self) -> float:
        return sum(l.total_gross for l in self.lines.values())

    @property
    def total_vat(self) -> float:
        return sum(l.total_vat for l in self.lines.values())

    @property
    def vorsteuer_material(self) -> float:
        """ESTV Ziffer 400."""
        return sum(l.total_vat for l in self.lines.values() if l.account_class == "material")

    @property
    def vorsteuer_investitionen(self) -> float:
        """ESTV Ziffer 405."""
        return sum(l.total_vat for l in self.lines.values()
                   if l.account_class == "investitionen")

    @property
    def vorsteuer_unclassified(self) -> float:
        return sum(l.total_vat for l in self.lines.values()
                   if l.account_class == "unclassified")

    def sorted_lines(self) -> List[VatLine]:
        """Lines sortiert nach (account_class, tax_rate desc, tax_code)."""
        order = {"material": 0, "investitionen": 1, "unclassified": 2}
        return sorted(
            self.lines.values(),
            key=lambda l: (order.get(l.account_class, 9), -l.tax_rate, l.tax_code),
        )


# =========================================================
# AGGREGATIONS-LOGIK
# =========================================================

def _split_gross(amount: float, rate_percent: float) -> Tuple[float, float, float]:
    """
    Bruttobetrag in (gross, net, vat) zerlegen.
    rate_percent: z.B. 8.1 fuer 8.1%.
    Bei 0% Rate: vat=0, net=gross.
    """
    if rate_percent <= 0:
        return amount, amount, 0.0
    factor = 1.0 + rate_percent / 100.0
    net = amount / factor
    vat = amount - net
    return amount, net, vat


def aggregate_bill_lines(
    bill_id_and_lines: List[Tuple[str, dict, List[dict]]],
    taxes_by_id: Dict[int, dict],
    accounts_by_id: Dict[int, dict],
    report: VatReport,
) -> None:
    """
    Verarbeitet eine Liste von (bill_id, bill_dict, line_items_list) und
    fuettert den Report. Bills ohne sinnvolle Daten landen als skipped.

    bill_dict.is_valid_proforma + status werden NICHT geprueft - das soll
    der Caller. Wir aggregieren alles was reinkommt.
    """
    for bill_id, bill, lines in bill_id_and_lines:
        if not lines:
            report.bills_skipped += 1
            report.warnings.append(f"Bill {bill_id}: keine Line-Items")
            continue

        bill_processed = False
        for line in lines:
            amount = line.get("amount")
            if amount is None:
                continue
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                continue
            if amount <= 0:
                continue

            tax_id = line.get("tax_id")
            account_id = line.get("booking_account_id")

            if not tax_id:
                report.warnings.append(
                    f"Bill {bill_id}: Zeile ohne MwSt-Code (Betrag {amount:.2f})"
                )
                continue

            tax = taxes_by_id.get(tax_id)
            if not tax:
                report.warnings.append(
                    f"Bill {bill_id}: unbekannter Tax-ID {tax_id}"
                )
                continue

            tax_code = tax.get("tax_code") or f"id-{tax_id}"
            tax_name = tax.get("tax_name") or tax_code
            tax_rate = float(tax.get("tax_rate") or 0.0)
            tax_type = tax.get("tax_type") or ""

            # Konto-Klasse
            account = accounts_by_id.get(account_id) if account_id else None
            account_nr = account.get("account_nr") if account else None
            klass = _account_class(account_nr)

            gross, net, vat = _split_gross(amount, tax_rate)
            line_obj = report.line_for(tax_code, tax_name, tax_rate, tax_type, klass)
            line_obj.add(gross, net, vat)
            bill_processed = True

        if bill_processed:
            report.bills_processed += 1
        else:
            report.bills_skipped += 1


# =========================================================
# HAUPT-ENTRY
# =========================================================

ProgressFn = Optional[callable]


async def build_vat_report(
    year: int,
    quarter: int,
    progress: ProgressFn = None,
    max_bills: int = 2000,
) -> VatReport:
    """
    Haupt-Funktion: laedt alle Bills im Quartal aus Bexio und aggregiert.

    Args:
        year, quarter: Berichts-Periode
        progress: optional async Callable(text) fuer User-Feedback
        max_bills: Schutz bei sehr grossen Mandaten

    Returns: VatReport mit allen Zeilen + Warnings.
    """
    # Lazy-Imports damit die Aggregations-Helper auch ohne DB/Bexio testbar
    # bleiben (test_mwst.py braucht kein supabase).
    from app import bexio as bexio_module
    from app import db

    start, end = quarter_date_range(year, quarter)
    report = VatReport(year, quarter, start, end)

    async def _say(text: str) -> None:
        if progress:
            await progress(text)
        logger.info(text)

    taxes = db.get_input_tax_codes()
    taxes_by_id: Dict[int, dict] = {t["bexio_tax_id"]: t for t in taxes}

    accounts = db.get_all_accounts()
    accounts_by_id: Dict[int, dict] = {a["bexio_account_id"]: a for a in accounts}

    if not taxes_by_id or not accounts_by_id:
        report.warnings.append(
            "Konten- oder MwSt-Cache leer. Fuehre erst /sync aus."
        )
        return report

    await _say(f"Lade Lieferantenrechnungen fuer {report.quarter_label}...")

    # Bills paginiert holen mit Datums-Filter
    bill_ids: List = []
    page = 1
    page_size = 500
    start_iso = start.isoformat()

    while len(bill_ids) < max_bills:
        try:
            response = await bexio_module.bexio.list_supplier_bills_page(
                page=page,
                limit=page_size,
                bill_date_start=start_iso,
            )
        except Exception as e:
            logger.error(f"Bill-Listing Seite {page} fehlgeschlagen: {e}")
            report.warnings.append(f"API-Fehler beim Laden Seite {page}: {e}")
            break

        items = response.get("data") or []
        if not items:
            break

        for item in items:
            bid = item.get("id")
            bill_date = item.get("bill_date")
            if not bid or not bill_date:
                continue
            # Bills die vor unserem Start liegen (bei sortierter Liste) -> stop
            if bill_date < start_iso:
                continue
            # Bills nach Period-End rausfiltern (start-Filter ist Bexio-API,
            # End-Filter machen wir clientseitig)
            if bill_date > end.isoformat():
                continue
            bill_ids.append(bid)
            if len(bill_ids) >= max_bills:
                break

        paging = response.get("paging") or {}
        page_count = paging.get("page_count")
        if page_count and page >= page_count:
            break
        if len(items) < page_size:
            break
        page += 1

    if not bill_ids:
        await _say("Keine Bills im Quartal gefunden.")
        return report

    await _say(f"{len(bill_ids)} Bills gefunden, lade Details...")

    # Pro Bill Details holen + aggregieren
    aggregated: List[Tuple[str, dict, List[dict]]] = []
    for i, bid in enumerate(bill_ids, start=1):
        if i % 25 == 0 or i == len(bill_ids):
            await _say(f"Verarbeite Bill {i}/{len(bill_ids)}...")
        try:
            detail = await bexio_module.bexio.get_supplier_bill(bid)
        except Exception as e:
            report.bills_skipped += 1
            report.warnings.append(f"Bill {bid}: Detail-Load failed ({e})")
            continue
        if not detail:
            report.bills_skipped += 1
            continue
        # DRAFT / nicht-gebuchte ueberspringen
        status = detail.get("status") or detail.get("state")
        if status and status.upper() in ("DRAFT", "OPEN"):
            # Open haben wir Defaults nicht zuverlaessig
            if status.upper() == "DRAFT":
                report.bills_skipped += 1
                continue
        lines = detail.get("line_items") or []
        aggregated.append((str(bid), detail, lines))

    aggregate_bill_lines(aggregated, taxes_by_id, accounts_by_id, report)

    logger.info(
        f"VAT-Report {report.quarter_label}: "
        f"processed={report.bills_processed}, skipped={report.bills_skipped}, "
        f"vat_total={report.total_vat:.2f}, warnings={len(report.warnings)}"
    )
    return report
