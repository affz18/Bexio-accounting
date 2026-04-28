"""
Tests fuer Phase 4 - camt.054-Parser und Reconcile-Matching-Engine.

Pure-Python-Tests, keine Network/DB-Mocks - nur Parser + Matcher.
"""
import sys
import types

import pytest


# Wir mocken app.config bevor app.camt/reconcile importiert werden, damit
# kein Supabase/.env geladen werden muss.
def _setup_config_mock() -> None:
    if "app.config" in sys.modules:
        return
    mod = types.ModuleType("app.config")

    class _Stub:
        log_level = "INFO"
        environment = "test"

    mod.settings = _Stub()  # type: ignore[attr-defined]
    sys.modules["app.config"] = mod


_setup_config_mock()


from app.camt import parse_camt, CamtParseError  # noqa: E402
from app.reconcile import find_matches  # noqa: E402


CAMT_QR_PAYMENT = b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.054.001.04">
  <BkToCstmrDbtCdtNtfctn>
    <GrpHdr><MsgId>MSG-1</MsgId><CreDtTm>2026-04-27T12:00:00</CreDtTm></GrpHdr>
    <Ntfctn>
      <Id>NTF-1</Id>
      <Acct><Id><IBAN>CH9300762011623852957</IBAN></Id></Acct>
      <Ntry>
        <Amt Ccy="CHF">659.40</Amt>
        <CdtDbtInd>DBIT</CdtDbtInd>
        <Sts>BOOK</Sts>
        <BookgDt><Dt>2026-04-25</Dt></BookgDt>
        <ValDt><Dt>2026-04-25</Dt></ValDt>
        <AcctSvcrRef>BANK-TX-001</AcctSvcrRef>
        <NtryDtls>
          <TxDtls>
            <Refs><EndToEndId>210000000003139471430009017</EndToEndId></Refs>
            <RltdPties>
              <Cdtr><Nm>SwissPlakat AG</Nm></Cdtr>
              <CdtrAcct><Id><IBAN>CH4800024024C9300062H</IBAN></Id></CdtrAcct>
            </RltdPties>
            <RmtInf>
              <Strd>
                <CdtrRefInf><Ref>21 00000 00003 13947 14300 09017</Ref></CdtrRefInf>
              </Strd>
              <Ustrd>Rechnung INV-2026-001</Ustrd>
            </RmtInf>
          </TxDtls>
        </NtryDtls>
      </Ntry>
    </Ntfctn>
  </BkToCstmrDbtCdtNtfctn>
</Document>
"""


def test_parse_simple_outgoing_qr_payment():
    txs = parse_camt(CAMT_QR_PAYMENT)
    assert len(txs) == 1
    tx = txs[0]
    assert tx.direction == "DBIT"
    assert tx.is_outgoing is True
    assert tx.amount == -659.40
    assert tx.absolute_amount == 659.40
    assert tx.currency == "CHF"
    assert tx.counterparty_name == "SwissPlakat AG"
    assert tx.counterparty_iban == "CH4800024024C9300062H"
    # Spaces in QR-Ref muessen rausgeparsed sein
    assert tx.structured_reference == "210000000003139471430009017"
    assert tx.bank_account_iban == "CH9300762011623852957"
    assert tx.transaction_id == "BANK-TX-001"


def test_parse_empty_xml_raises():
    with pytest.raises(CamtParseError):
        parse_camt(b"")


def test_parse_invalid_xml_raises():
    with pytest.raises(CamtParseError):
        parse_camt(b"<not-camt/>")


def _invoice(invoice_id="i1", **overrides):
    base = {
        "id": invoice_id,
        "vendor_name": "SwissPlakat AG",
        "total_amount": 659.40,
        "iban": "CH4800024024C9300062H",
        "reference_number": "210000000003139471430009017",
        "invoice_date": "2026-04-15",
        "due_date": "2026-05-15",
    }
    base.update(overrides)
    return base


def test_match_qr_reference_exact():
    txs = parse_camt(CAMT_QR_PAYMENT)
    candidates = find_matches(txs[0], [_invoice()])
    assert len(candidates) == 1
    c = candidates[0]
    assert c.strategy == "qr_reference"
    assert c.confidence >= 0.95
    assert c.pending_invoice_id == "i1"


def test_match_no_candidates_when_amount_diverges():
    txs = parse_camt(CAMT_QR_PAYMENT)
    # Andere Rechnung: kein QR-Match, IBAN faked aber Amount falsch
    inv = _invoice(
        reference_number="999",
        total_amount=100.00,
        iban="CH0000000000000000000",
        vendor_name="Nichts AG",
    )
    candidates = find_matches(txs[0], [inv])
    assert candidates == []


def test_match_iban_fallback_when_no_qr_match():
    txs = parse_camt(CAMT_QR_PAYMENT)
    # Rechnung ohne QR-Ref aber gleiche IBAN + gleicher Betrag
    inv = _invoice(reference_number=None)
    candidates = find_matches(txs[0], [inv])
    assert len(candidates) == 1
    assert candidates[0].strategy == "iban_amount_date"
    assert 0.7 <= candidates[0].confidence <= 0.95


def test_match_vendor_name_fuzzy():
    txs = parse_camt(CAMT_QR_PAYMENT)
    # Kein QR, andere IBAN, aber Name aehnlich + Betrag stimmt
    inv = _invoice(
        reference_number=None,
        iban="CH0000000000000000000",
        vendor_name="SwissPlakat",  # ohne "AG", trotzdem matchen
    )
    candidates = find_matches(txs[0], [inv])
    assert len(candidates) == 1
    assert candidates[0].strategy == "vendor_amount_date"
    assert 0.5 <= candidates[0].confidence < 0.9


def test_no_match_for_incoming_credit():
    """CRDT-Bewegungen (Kunden-Eingaenge) sollen nicht gegen Lieferanten
    gematcht werden."""
    crdt_xml = CAMT_QR_PAYMENT.replace(b"<CdtDbtInd>DBIT</CdtDbtInd>",
                                       b"<CdtDbtInd>CRDT</CdtDbtInd>")
    txs = parse_camt(crdt_xml)
    assert txs[0].is_outgoing is False
    candidates = find_matches(txs[0], [_invoice()])
    assert candidates == []
