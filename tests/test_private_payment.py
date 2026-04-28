"""
Tests fuer das 'Privat bezahlt'-Feature.

Kern: das Bexio create_manual_journal_entry baut den korrekten Payload
zusammen. Wir mocken _request und pruefen dass die Buchungs-Logik
(Soll/Haben/Betrag/Datum/MwSt) sauber durchkommt.
"""
import sys
import types
from unittest.mock import AsyncMock

import pytest


def _setup_config_mock() -> None:
    if "app.config" in sys.modules:
        return
    mod = types.ModuleType("app.config")

    class _Stub:
        log_level = "INFO"
        environment = "test"
        bexio_api_token = "test-token"
        bexio_api_base_url = "https://api.bexio.test"
        bexio_private_payment_credit_account_nr = "2100"

    mod.settings = _Stub()  # type: ignore[attr-defined]
    sys.modules["app.config"] = mod


_setup_config_mock()

from app import bexio as bexio_module  # noqa: E402


@pytest.fixture
def client():
    """Frischer BexioClient pro Test."""
    return bexio_module.BexioClient()


@pytest.mark.asyncio
async def test_manual_entry_payload_minimal(client, monkeypatch):
    """Ohne tax_id und reference_nr: Payload enthaelt nur Pflichtfelder."""
    captured = {}

    async def fake_request(method, path, params=None, json=None, max_retries=2):
        captured["method"] = method
        captured["path"] = path
        captured["json"] = json
        return {"id": "mje-123"}

    monkeypatch.setattr(client, "_request", fake_request)

    result = await client.create_manual_journal_entry(
        date="2026-04-28",
        debit_account_id=42,
        credit_account_id=99,
        amount=123.45,
        description="Beleg Migros 28.04.2026 - privat durch Inhaber bezahlt",
    )

    assert result == {"id": "mje-123"}
    assert captured["method"] == "POST"
    assert captured["path"] == "/3.0/accounting/manual_entries"

    payload = captured["json"]
    assert payload["type"] == "manual_single_entry"
    assert payload["date"] == "2026-04-28"
    assert "reference_nr" not in payload  # Nicht gesetzt -> nicht im Payload

    entries = payload["entries"]
    assert len(entries) == 1
    e = entries[0]
    assert e["debit_account_id"] == 42
    assert e["credit_account_id"] == 99
    assert e["amount"] == 123.45
    assert e["currency_id"] == 1  # Default CHF
    assert e["currency_factor"] == 1
    assert "tax_id" not in e
    assert "Migros" in e["description"]


@pytest.mark.asyncio
async def test_manual_entry_payload_with_tax_and_ref(client, monkeypatch):
    """Mit tax_id + reference_nr: Bexio kann MwSt auto-splitten."""
    captured = {}

    async def fake_request(method, path, params=None, json=None, max_retries=2):
        captured["json"] = json
        return {"id": "mje-456"}

    monkeypatch.setattr(client, "_request", fake_request)

    await client.create_manual_journal_entry(
        date="2026-03-15",
        debit_account_id=6500,
        credit_account_id=2100,
        amount=100.00,
        description="Test",
        tax_id=7,
        reference_nr="INV-2026-001",
    )

    payload = captured["json"]
    assert payload["reference_nr"] == "INV-2026-001"
    assert payload["entries"][0]["tax_id"] == 7


@pytest.mark.asyncio
async def test_manual_entry_amount_rounding(client, monkeypatch):
    """Floating-Point-Eingaenge muessen auf 2 Nachkommastellen gerundet werden."""
    captured = {}

    async def fake_request(method, path, params=None, json=None, max_retries=2):
        captured["json"] = json
        return {"id": "x"}

    monkeypatch.setattr(client, "_request", fake_request)

    await client.create_manual_journal_entry(
        date="2026-04-28",
        debit_account_id=1,
        credit_account_id=2,
        amount=1.23456789,
        description="Rounding-Check",
    )

    assert captured["json"]["entries"][0]["amount"] == 1.23


@pytest.mark.asyncio
async def test_manual_entry_description_truncated(client, monkeypatch):
    """Sehr lange Beschreibungen muessen auf 200 Zeichen gekappt werden."""
    captured = {}

    async def fake_request(method, path, params=None, json=None, max_retries=2):
        captured["json"] = json
        return {"id": "x"}

    monkeypatch.setattr(client, "_request", fake_request)

    long_desc = "X" * 500
    await client.create_manual_journal_entry(
        date="2026-04-28",
        debit_account_id=1,
        credit_account_id=2,
        amount=10.0,
        description=long_desc,
    )

    assert len(captured["json"]["entries"][0]["description"]) <= 200


@pytest.mark.asyncio
async def test_manual_entry_propagates_bexio_error(client, monkeypatch):
    """Wenn Bexio einen Fehler wirft, muss er an den Caller propagieren."""
    async def fake_request(method, path, params=None, json=None, max_retries=2):
        raise bexio_module.BexioError(
            "Bexio API Fehler (400)",
            status_code=400,
            response_body='{"detail":"invalid debit_account_id"}',
        )

    monkeypatch.setattr(client, "_request", fake_request)

    with pytest.raises(bexio_module.BexioError):
        await client.create_manual_journal_entry(
            date="2026-04-28",
            debit_account_id=999999,
            credit_account_id=2,
            amount=10.0,
            description="Soll-Konto existiert nicht",
        )
