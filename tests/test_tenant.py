"""
Tests fuer Multi-Tenant-Foundation (Phase B1).

Decken: Tenant Pydantic-Model. DB-Funktionen sind ohne echten Supabase-Client
nicht trivial testbar - die werden in Block 1B (Code-Refactor) durch
Integration-Tests gegen eine Test-DB abgedeckt.
"""
import sys
import types

import pytest


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

from app.models import Tenant  # noqa: E402


def test_tenant_minimal():
    """Tenant kann mit nur id+display_name erstellt werden."""
    t = Tenant(id="visioskin", display_name="VisioSkin")
    assert t.id == "visioskin"
    assert t.display_name == "VisioSkin"
    assert t.is_active is True
    assert t.imap_enabled is False
    assert t.imap_port == 993
    assert t.imap_folder == "INBOX"
    assert t.private_payment_credit_account_nr == "2100"


def test_tenant_full():
    """Alle Felder gesetzt - Roundtrip durch Pydantic."""
    t = Tenant(
        id="klein-ag",
        display_name="Klein AG",
        bexio_api_token="bex_xxx",
        bexio_company_id="cmp_123",
        imap_enabled=True,
        imap_host="imap.example.com",
        imap_user="info@klein.ch",
        imap_password="secret",
        telegram_notify_chat_id=123456,
        company_name="Klein AG",
        company_uid="CHE-123.456.789",
        company_name_aliases="Klein,Klein AG,Klein Aktiengesellschaft",
    )
    assert t.id == "klein-ag"
    assert t.imap_enabled is True
    assert t.imap_port == 993  # Default
    assert t.telegram_notify_chat_id == 123456
    assert t.company_uid == "CHE-123.456.789"


def test_tenant_default_private_account():
    """Default fuer Privat-bezahlt-Konto ist 2100."""
    t = Tenant(id="x", display_name="X")
    assert t.private_payment_credit_account_nr == "2100"


def test_tenant_serialization():
    """to_dict / model_dump sollte alle Felder enthalten."""
    t = Tenant(id="visioskin", display_name="VisioSkin")
    data = t.model_dump()
    assert data["id"] == "visioskin"
    assert "bexio_api_token" in data
    assert "imap_enabled" in data
    assert data["is_active"] is True


def test_tenant_aliases_field():
    """company_name_aliases ist Text - Komma-separiert wird im Code geparst."""
    t = Tenant(
        id="x",
        display_name="X",
        company_name_aliases="X AG,X Solutions GmbH,X Holding",
    )
    aliases = [a.strip() for a in (t.company_name_aliases or "").split(",")]
    assert len(aliases) == 3
    assert "X AG" in aliases
