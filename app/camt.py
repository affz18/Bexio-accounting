"""
camt.054 (ISO 20022 Debit/Credit Notification) Parser.

Parsed eine camt-Datei in eine Liste von BankTransaction-Objekten. Robust
gegen verschiedene camt.054-Versionen (.001.04, .001.06, .001.08) - die
Schweizer Banken liefern unterschiedliche Versionen, das Schema-Layout fuer
unsere Felder ist aber stabil.

Wir nutzen defusedxml statt stdlib xml.etree, weil camt-Dateien
prinzipiell als untrusted gelten (User-Upload).

Wichtig: camt.053 hat Statement-Layout (Kontoauszug), camt.054 ist
Notification (einzelne Bewegungen). Wir akzeptieren beide - das XML-Layout
fuer unsere Felder ist quasi identisch.
"""
from datetime import date, datetime
from typing import List, Optional

from defusedxml import ElementTree as ET

from app.models import BankTransaction
from app.utils import setup_logger


logger = setup_logger(__name__)


class CamtParseError(Exception):
    """Fehler beim Parsen einer camt-Datei."""
    pass


# Wir matchen Tags nach lokalem Namen statt mit fixen Namespaces, weil
# verschiedene camt-Versionen unterschiedliche namespace-URIs haben.
def _local(tag: str) -> str:
    """Holt den lokalen Tag-Namen ohne Namespace."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _find(elem, *names) -> Optional["ET.Element"]:
    """Findet ein Sub-Element ueber mehrere Ebenen, namespace-agnostisch."""
    if elem is None:
        return None
    current = elem
    for name in names:
        next_elem = None
        for child in current:
            if _local(child.tag) == name:
                next_elem = child
                break
        if next_elem is None:
            return None
        current = next_elem
    return current


def _findall(elem, name) -> List["ET.Element"]:
    """Listet alle direkten Kinder mit gegebenem lokalen Tag."""
    if elem is None:
        return []
    return [c for c in elem if _local(c.tag) == name]


def _text(elem, *names) -> Optional[str]:
    """Liest den Text eines verschachtelten Elements, oder None."""
    found = _find(elem, *names)
    if found is None or found.text is None:
        return None
    txt = found.text.strip()
    return txt or None


def _parse_date(txt: Optional[str]) -> Optional[date]:
    """camt-Datums sind YYYY-MM-DD oder ISO-8601 mit Zeit-Anteil."""
    if not txt:
        return None
    txt = txt.strip()
    if not txt:
        return None
    # Versuch: pures Datum
    try:
        return datetime.strptime(txt[:10], "%Y-%m-%d").date()
    except ValueError:
        pass
    # Versuch: ISO mit Zeit
    try:
        return datetime.fromisoformat(txt.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _extract_account_iban(notification: "ET.Element") -> Optional[str]:
    """Holt die IBAN des Kontos auf das sich die camt bezieht (Acct/Id/IBAN)."""
    return _text(notification, "Acct", "Id", "IBAN")


def _extract_counterparty(tx_dtls: "ET.Element", direction: str) -> tuple:
    """
    Extrahiert (counterparty_name, counterparty_iban) aus RltdPties.

    Bei DBIT (outgoing) ist die Gegenpartei der Empfaenger (Cdtr).
    Bei CRDT (incoming) ist die Gegenpartei der Sender (Dbtr).
    """
    rltd = _find(tx_dtls, "RltdPties")
    if rltd is None:
        return None, None

    if direction == "DBIT":
        party = _find(rltd, "Cdtr")
        acct = _find(rltd, "CdtrAcct")
    else:
        party = _find(rltd, "Dbtr")
        acct = _find(rltd, "DbtrAcct")

    name = None
    if party is not None:
        # Manche Banken packen Pty in Cdtr/Dbtr, andere direkt
        name = _text(party, "Pty", "Nm") or _text(party, "Nm")

    iban = None
    if acct is not None:
        iban = _text(acct, "Id", "IBAN")

    return name, iban


def _extract_remittance(tx_dtls: "ET.Element") -> tuple:
    """
    Liest QR/ESR-Referenz (Strd/CdtrRefInf/Ref) und freien
    Verwendungszweck (Ustrd) aus RmtInf.

    Returns: (structured_reference, unstructured_text)
    """
    rmt = _find(tx_dtls, "RmtInf")
    if rmt is None:
        return None, None

    structured = None
    strd = _find(rmt, "Strd")
    if strd is not None:
        structured = _text(strd, "CdtrRefInf", "Ref")
        if structured:
            # Schweizer QR/ESR-Referenz hat keine Leerzeichen
            structured = structured.replace(" ", "")

    unstructured_parts = [
        u.text.strip()
        for u in _findall(rmt, "Ustrd")
        if u.text and u.text.strip()
    ]
    unstructured = " ".join(unstructured_parts) if unstructured_parts else None

    return structured, unstructured


def _extract_transaction_id(ntry: "ET.Element", tx_dtls: "ET.Element") -> Optional[str]:
    """
    Bevorzugt AcctSvcrRef (bank-eindeutig) aus dem Ntry, fallback auf
    TxId aus den Details. Letzter Fallback: kombiniert aus E2E-Id.
    """
    # Auf Ntry-Ebene: AcctSvcrRef ist die Buchungsreferenz der Bank
    asr = _text(ntry, "AcctSvcrRef")
    if asr:
        return asr

    # In TxDtls/Refs/AcctSvcrRef oder TxId
    refs = _find(tx_dtls, "Refs")
    if refs is not None:
        for key in ("AcctSvcrRef", "TxId", "InstrId"):
            val = _text(refs, key)
            if val:
                return val

    return None


def _parse_entry(ntry: "ET.Element") -> List[BankTransaction]:
    """
    Parst ein einzelnes <Ntry>-Element. Eine Ntry kann mehrere TxDtls
    haben (Sammelbuchungen) - wir geben dann mehrere Transaktionen zurueck.
    """
    # Aggregat-Felder aus Ntry-Ebene
    amt_elem = _find(ntry, "Amt")
    if amt_elem is None or not amt_elem.text:
        return []
    try:
        entry_amount = float(amt_elem.text)
    except ValueError:
        return []
    currency = (amt_elem.get("Ccy") or "CHF").upper()

    direction = _text(ntry, "CdtDbtInd")
    if direction not in ("DBIT", "CRDT"):
        return []

    booking_date = _parse_date(_text(ntry, "BookgDt", "Dt")) \
        or _parse_date(_text(ntry, "BookgDt", "DtTm"))
    if booking_date is None:
        return []
    value_date = _parse_date(_text(ntry, "ValDt", "Dt")) \
        or _parse_date(_text(ntry, "ValDt", "DtTm"))

    # NtryDtls > TxDtls (kann mehrere haben)
    tx_dtls_list: List["ET.Element"] = []
    for ntry_dtls in _findall(ntry, "NtryDtls"):
        tx_dtls_list.extend(_findall(ntry_dtls, "TxDtls"))

    # Wenn keine TxDtls existieren, Fallback auf Ntry-Level
    if not tx_dtls_list:
        signed = entry_amount if direction == "CRDT" else -entry_amount
        return [BankTransaction(
            transaction_id=_text(ntry, "AcctSvcrRef"),
            booking_date=booking_date,
            value_date=value_date,
            amount=signed,
            currency=currency,
            direction=direction,
        )]

    results: List[BankTransaction] = []
    for tx_dtls in tx_dtls_list:
        # Pro-TxDtls Betrag (kann von Ntry-Sum abweichen bei Sammelbuchung)
        tx_amt_elem = _find(tx_dtls, "Amt") or _find(tx_dtls, "AmtDtls", "TxAmt", "Amt")
        if tx_amt_elem is not None and tx_amt_elem.text:
            try:
                tx_amount = float(tx_amt_elem.text)
                tx_currency = (tx_amt_elem.get("Ccy") or currency).upper()
            except ValueError:
                tx_amount = entry_amount
                tx_currency = currency
        else:
            tx_amount = entry_amount
            tx_currency = currency

        signed = tx_amount if direction == "CRDT" else -tx_amount

        cp_name, cp_iban = _extract_counterparty(tx_dtls, direction)
        structured, unstructured = _extract_remittance(tx_dtls)
        tx_id = _extract_transaction_id(ntry, tx_dtls)

        # E2E-Id ist bei QR-Zahlungen oft = QR-Ref
        e2e = _text(tx_dtls, "Refs", "EndToEndId")
        # Manche Banken setzen "NOTPROVIDED" - dann ignorieren
        if e2e and e2e.upper() in ("NOTPROVIDED", "NICHTERTEILT"):
            e2e = None

        results.append(BankTransaction(
            transaction_id=tx_id,
            end_to_end_id=e2e,
            structured_reference=structured,
            booking_date=booking_date,
            value_date=value_date,
            amount=signed,
            currency=tx_currency,
            direction=direction,
            counterparty_name=cp_name,
            counterparty_iban=cp_iban,
            remittance_unstructured=unstructured,
        ))

    return results


def parse_camt(xml_bytes: bytes) -> List[BankTransaction]:
    """
    Parst eine camt.054 (oder .053) Datei und gibt alle Bank-Bewegungen
    als BankTransaction-Liste zurueck.

    Die Konto-IBAN wird in jedes Result als bank_account_iban gesetzt,
    damit nachgelagerte Speicherung pro IBAN deduplizieren kann.

    Raises:
        CamtParseError: bei kaputten/leeren XML-Dateien.
    """
    if not xml_bytes:
        raise CamtParseError("Leere Datei")

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise CamtParseError(f"Ungueltiges XML: {e}")

    # Document > BkToCstmrDbtCdtNtfctn (camt.054) ODER
    # Document > BkToCstmrStmt (camt.053)
    # Dann jeweils eine oder mehrere Ntfctn / Stmt
    container = None
    for child in root:
        ln = _local(child.tag)
        if ln in ("BkToCstmrDbtCdtNtfctn", "BkToCstmrStmt"):
            container = child
            break

    if container is None:
        raise CamtParseError(
            "Kein camt.054 / camt.053 Container gefunden "
            "(BkToCstmrDbtCdtNtfctn / BkToCstmrStmt)"
        )

    transactions: List[BankTransaction] = []
    notifications = _findall(container, "Ntfctn") + _findall(container, "Stmt")

    for ntfctn in notifications:
        account_iban = _extract_account_iban(ntfctn)
        for ntry in _findall(ntfctn, "Ntry"):
            for tx in _parse_entry(ntry):
                tx.bank_account_iban = account_iban
                transactions.append(tx)

    logger.info(
        f"camt-Parser: {len(transactions)} Transaktionen aus "
        f"{len(notifications)} Notification(s) extrahiert"
    )
    return transactions
