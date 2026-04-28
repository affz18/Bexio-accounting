"""
Matching-Engine fuer Bank-Reconciliation (Phase 4).

Vergleicht parsed BankTransactions gegen offene pending_invoices und
liefert MatchCandidates mit Confidence-Score und Strategie-Begruendung.

Strategien, in Reihenfolge der Confidence:

1. QR-Referenz (~0.99) - structured_reference == pending_invoice.reference_number
2. End-to-End-Id (~0.95) - end_to_end_id == reference_number
3. IBAN + Betrag (~0.85) - counterparty_iban + amount im Toleranz-Fenster
4. Vendor-Name + Betrag (~0.65) - fuzzy name-match + amount

Ein Confidence-Score < MIN_CONFIDENCE wird verworfen. Pro Bank-TX kann es
mehrere Kandidaten geben (z.B. zwei offene Rechnungen mit gleichem Betrag);
der User entscheidet dann.
"""
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from app.models import BankTransaction, MatchCandidate
from app.utils import setup_logger


logger = setup_logger(__name__)


# Minimum-Confidence damit ein Kandidat zurueckgegeben wird.
# Darunter rauschen wir den User nicht zu.
MIN_CONFIDENCE = 0.5

# Maximale Differenz zwischen Bank-Betrag und Rechnungs-Betrag fuer einen
# Match. Currency-Conversion-Rundungen oder Spesen koennen kleine Differenzen
# erzeugen. Default 5 Rappen.
DEFAULT_AMOUNT_TOLERANCE_CHF = 0.05

# Wie viele Tage darf zwischen Rechnungsdatum und Buchungsdatum liegen?
DEFAULT_DATE_WINDOW_DAYS = 60


def _normalize_iban(iban: Optional[str]) -> Optional[str]:
    if not iban:
        return None
    return iban.replace(" ", "").upper()


def _normalize_qr_ref(ref: Optional[str]) -> Optional[str]:
    if not ref:
        return None
    cleaned = "".join(c for c in ref if c.isdigit())
    return cleaned or None


def _normalize_name(name: Optional[str]) -> str:
    """Lower-case, nur alphanumerisch + Spaces, trim."""
    if not name:
        return ""
    out = []
    for c in name.lower():
        if c.isalnum() or c.isspace():
            out.append(c)
    return " ".join("".join(out).split())


def _amounts_match(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) <= tolerance + 1e-9


def _name_similarity(a: str, b: str) -> float:
    """
    Simple Token-Overlap-Score. 1.0 bei vollstaendiger Ueberlappung,
    0.0 bei null gemeinsamen Tokens.

    Wir machen kein Levenshtein etc. - die Banken liefern die Vendor-Namen
    in der Regel sauber, eine Token-Set-Intersection reicht.
    Vendor-Endungen wie "AG"/"GmbH" zaehlen wir nicht.
    """
    stopwords = {"ag", "gmbh", "sa", "sarl", "gnbh", "kg", "co", "ltd", "inc"}
    tokens_a = {t for t in _normalize_name(a).split() if t not in stopwords}
    tokens_b = {t for t in _normalize_name(b).split() if t not in stopwords}
    if not tokens_a or not tokens_b:
        return 0.0
    inter = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(inter) / len(union)


def _within_date_window(
    bank_date: date,
    invoice_date_str: Optional[str],
    window_days: int,
) -> bool:
    """Prueft ob bank_date innerhalb +/- window_days um invoice_date liegt."""
    if not invoice_date_str:
        return True  # Kein Datum -> wir sind tolerant
    try:
        inv_date = date.fromisoformat(invoice_date_str[:10])
    except (ValueError, TypeError):
        return True
    delta = abs((bank_date - inv_date).days)
    return delta <= window_days


def _candidate(
    invoice: Dict[str, Any],
    confidence: float,
    strategy: str,
    reason: str,
) -> MatchCandidate:
    return MatchCandidate(
        pending_invoice_id=str(invoice["id"]),
        confidence=round(confidence, 3),
        strategy=strategy,
        reason=reason,
        invoice_vendor=invoice.get("vendor_name"),
        invoice_amount=invoice.get("total_amount"),
        invoice_reference=invoice.get("reference_number"),
    )


def find_matches(
    bank_tx: BankTransaction,
    open_invoices: List[Dict[str, Any]],
    amount_tolerance: float = DEFAULT_AMOUNT_TOLERANCE_CHF,
    date_window_days: int = DEFAULT_DATE_WINDOW_DAYS,
) -> List[MatchCandidate]:
    """
    Sucht passende offene Rechnungen fuer eine Bank-Transaktion.
    Nur DBIT (outgoing) wird gematcht - CRDT sind Kunden-Zahlungseingaenge,
    die behandeln wir spaeter (Phase 4b).

    open_invoices: Liste von Dicts aus pending_invoices Tabelle. Erwartete
                   Felder: id, vendor_name, total_amount, iban, reference_number,
                   invoice_date, due_date, status.

    Returns: nach Confidence absteigend sortierte Liste. Leer wenn nichts
             ueber MIN_CONFIDENCE.
    """
    if not bank_tx.is_outgoing:
        return []
    if not open_invoices:
        return []

    bank_amount = bank_tx.absolute_amount
    bank_iban = _normalize_iban(bank_tx.counterparty_iban)
    bank_qr = _normalize_qr_ref(bank_tx.structured_reference)
    bank_e2e = _normalize_qr_ref(bank_tx.end_to_end_id)
    bank_name = bank_tx.counterparty_name or ""

    candidates: List[MatchCandidate] = []

    for invoice in open_invoices:
        invoice_amount = invoice.get("total_amount")
        if invoice_amount is None:
            continue
        try:
            invoice_amount = float(invoice_amount)
        except (TypeError, ValueError):
            continue

        invoice_qr = _normalize_qr_ref(invoice.get("reference_number"))
        invoice_iban = _normalize_iban(invoice.get("iban"))
        invoice_vendor = invoice.get("vendor_name") or ""

        amounts_close = _amounts_match(bank_amount, invoice_amount, amount_tolerance)

        # ----- Strategie 1: QR-Referenz -----
        if invoice_qr and bank_qr and invoice_qr == bank_qr:
            confidence = 0.99 if amounts_close else 0.85
            reason_amt = "Betrag exakt" if amounts_close else (
                f"Betrag-Differenz {abs(bank_amount - invoice_amount):.2f}"
            )
            candidates.append(_candidate(
                invoice,
                confidence,
                "qr_reference",
                f"QR-Ref-Match {invoice_qr[-7:]}, {reason_amt}",
            ))
            continue

        # ----- Strategie 2: End-to-End-Id == QR-Ref -----
        if invoice_qr and bank_e2e and invoice_qr == bank_e2e:
            confidence = 0.95 if amounts_close else 0.78
            candidates.append(_candidate(
                invoice,
                confidence,
                "qr_reference",
                f"E2E-Id matcht QR-Ref {invoice_qr[-7:]}",
            ))
            continue

        # Ohne QR-Match brauchen wir mind. Betrag-Match und Datum-Fenster
        if not amounts_close:
            continue

        within_window = _within_date_window(
            bank_tx.booking_date,
            invoice.get("invoice_date") or invoice.get("due_date"),
            date_window_days,
        )

        # ----- Strategie 3: IBAN + Betrag + Datum -----
        if invoice_iban and bank_iban and invoice_iban == bank_iban:
            confidence = 0.88 if within_window else 0.70
            candidates.append(_candidate(
                invoice,
                confidence,
                "iban_amount_date",
                f"IBAN exakt + Betrag {bank_amount:.2f} CHF",
            ))
            continue

        # ----- Strategie 4: Vendor-Name + Betrag + Datum -----
        if not within_window:
            continue
        sim = _name_similarity(bank_name, invoice_vendor)
        if sim >= 0.5:
            # 0.5 Token-Overlap -> 0.65 Confidence
            # 1.0 Token-Overlap -> 0.80 Confidence
            confidence = 0.55 + 0.25 * sim
            candidates.append(_candidate(
                invoice,
                confidence,
                "vendor_amount_date",
                f"Vendor-Name aehnlich ({sim:.0%}) + Betrag {bank_amount:.2f} CHF",
            ))

    candidates = [c for c in candidates if c.confidence >= MIN_CONFIDENCE]
    candidates.sort(key=lambda c: c.confidence, reverse=True)

    if candidates:
        logger.info(
            f"Match: TX {bank_tx.transaction_id} ({bank_tx.absolute_amount:.2f} "
            f"{bank_tx.currency} an {bank_tx.counterparty_name or '?'}) -> "
            f"{len(candidates)} Kandidat(en), bester {candidates[0].confidence:.2f} "
            f"via {candidates[0].strategy}"
        )

    return candidates


def match_transactions(
    transactions: List[BankTransaction],
    open_invoices: List[Dict[str, Any]],
    **kwargs,
) -> Dict[str, List[MatchCandidate]]:
    """
    Batch-Matching. Returns dict {transaction_id: [candidates...]}.
    Bank-Transaktionen ohne TxId fallen raus (koennen wir nicht stabil
    speichern).
    """
    result: Dict[str, List[MatchCandidate]] = {}
    for tx in transactions:
        if not tx.transaction_id:
            continue
        if not tx.is_outgoing:
            continue
        candidates = find_matches(tx, open_invoices, **kwargs)
        if candidates:
            result[tx.transaction_id] = candidates
    return result
