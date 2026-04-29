"""
Tests fuer das MWST-Modul.

Decken: Quartal-Parsing, Datums-Range, Aggregations-Logik. Alles ohne
Bexio-API-Calls.
"""
import sys
import types
from datetime import date

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
        supabase_url = "https://test.supabase.co"
        supabase_service_role_key = "test-key"

    mod.settings = _Stub()  # type: ignore[attr-defined]
    sys.modules["app.config"] = mod


_setup_config_mock()


from app.mwst import (  # noqa: E402
    parse_quarter_string,
    quarter_date_range,
    current_quarter,
    previous_quarter,
    aggregate_bill_lines,
    VatReport,
    _account_class,
    _split_gross,
)


# =========================================================
# QUARTAL-PARSING
# =========================================================

@pytest.mark.parametrize("input_str,expected", [
    ("2026Q3", (2026, 3)),
    ("2026q3", (2026, 3)),
    ("Q3 2026", (2026, 3)),
    ("Q3/2026", (2026, 3)),
    ("3/2026", (2026, 3)),
    ("2026-Q3", (2026, 3)),
    ("2026/3", (2026, 3)),
    ("  2026Q1  ", (2026, 1)),
])
def test_parse_quarter_valid(input_str, expected):
    assert parse_quarter_string(input_str) == expected


@pytest.mark.parametrize("invalid", [
    "",
    "2026",
    "Q5 2026",
    "2026Q0",
    "abcdef",
    "1999Q1",  # vor Range
    "2200Q1",  # nach Range
])
def test_parse_quarter_invalid(invalid):
    with pytest.raises(ValueError):
        parse_quarter_string(invalid)


# =========================================================
# QUARTAL-DATE-RANGE
# =========================================================

def test_quarter_q1_range():
    s, e = quarter_date_range(2026, 1)
    assert s == date(2026, 1, 1)
    assert e == date(2026, 3, 31)


def test_quarter_q2_range():
    s, e = quarter_date_range(2026, 2)
    assert s == date(2026, 4, 1)
    assert e == date(2026, 6, 30)


def test_quarter_q3_range():
    s, e = quarter_date_range(2026, 3)
    assert s == date(2026, 7, 1)
    assert e == date(2026, 9, 30)


def test_quarter_q4_range():
    s, e = quarter_date_range(2026, 4)
    assert s == date(2026, 10, 1)
    assert e == date(2026, 12, 31)


def test_quarter_invalid():
    with pytest.raises(ValueError):
        quarter_date_range(2026, 5)


# =========================================================
# ACCOUNT-CLASS-MAPPING (ESTV Ziffer 400 vs 405)
# =========================================================

@pytest.mark.parametrize("nr,expected", [
    ("4000", "material"),
    ("4400", "material"),
    ("4900", "material"),
    ("5000", "investitionen"),
    ("6500", "investitionen"),
    ("7000", "investitionen"),
    ("8000", "investitionen"),
    ("1020", "unclassified"),
    ("2000", "unclassified"),
    ("3200", "unclassified"),
    (None, "unclassified"),
    ("", "unclassified"),
])
def test_account_class(nr, expected):
    assert _account_class(nr) == expected


# =========================================================
# GROSS-NET-VAT-SPLIT
# =========================================================

def test_split_gross_8_1_percent():
    """108.10 brutto bei 8.1% -> 100.00 netto, 8.10 vat."""
    gross, net, vat = _split_gross(108.10, 8.1)
    assert gross == 108.10
    assert round(net, 2) == 100.00
    assert round(vat, 2) == 8.10


def test_split_gross_zero_rate():
    """Bei 0%: vat = 0, net = gross."""
    gross, net, vat = _split_gross(100.00, 0.0)
    assert gross == 100.00
    assert net == 100.00
    assert vat == 0.0


def test_split_gross_2_6_percent():
    """102.60 brutto bei 2.6% reduziert -> 100.00 netto, 2.60 vat."""
    gross, net, vat = _split_gross(102.60, 2.6)
    assert round(net, 2) == 100.00
    assert round(vat, 2) == 2.60


# =========================================================
# AGGREGATION
# =========================================================

def _setup_caches():
    """Test-Daten fuer Tax/Account-Lookups."""
    taxes = {
        1: {"bexio_tax_id": 1, "tax_code": "VSTN",
            "tax_name": "Vorsteuer Normal", "tax_rate": 8.1, "tax_type": "pre_tax"},
        2: {"bexio_tax_id": 2, "tax_code": "VSTR",
            "tax_name": "Vorsteuer Reduziert", "tax_rate": 2.6, "tax_type": "pre_tax"},
    }
    accounts = {
        100: {"bexio_account_id": 100, "account_nr": "4000", "account_name": "Material"},
        200: {"bexio_account_id": 200, "account_nr": "6500", "account_name": "Buero"},
    }
    return taxes, accounts


def _bill(bill_id, line_items):
    """Test-Helper: bill-detail-Dict mit line_items."""
    return (str(bill_id), {"id": bill_id, "status": "BOOKED"}, line_items)


def test_aggregate_single_bill_single_line():
    taxes, accounts = _setup_caches()
    report = VatReport(2026, 3, date(2026, 7, 1), date(2026, 9, 30))

    bills = [_bill(1, [
        {"amount": 108.10, "tax_id": 1, "booking_account_id": 100},
    ])]
    aggregate_bill_lines(bills, taxes, accounts, report)

    assert report.bills_processed == 1
    assert report.bills_skipped == 0
    assert len(report.lines) == 1
    line = list(report.lines.values())[0]
    assert line.line_count == 1
    assert round(line.total_gross, 2) == 108.10
    assert round(line.total_net, 2) == 100.00
    assert round(line.total_vat, 2) == 8.10
    assert line.account_class == "material"
    assert round(report.vorsteuer_material, 2) == 8.10
    assert report.vorsteuer_investitionen == 0


def test_aggregate_splits_by_account_class():
    taxes, accounts = _setup_caches()
    report = VatReport(2026, 3, date(2026, 7, 1), date(2026, 9, 30))

    bills = [
        _bill(1, [{"amount": 108.10, "tax_id": 1, "booking_account_id": 100}]),  # 4000 -> material
        _bill(2, [{"amount": 216.20, "tax_id": 1, "booking_account_id": 200}]),  # 6500 -> investitionen
    ]
    aggregate_bill_lines(bills, taxes, accounts, report)

    assert report.bills_processed == 2
    assert round(report.vorsteuer_material, 2) == 8.10
    assert round(report.vorsteuer_investitionen, 2) == 16.20
    # Zwei separate Lines weil unterschiedliche account_class
    assert len(report.lines) == 2


def test_aggregate_warns_on_missing_tax_id():
    taxes, accounts = _setup_caches()
    report = VatReport(2026, 3, date(2026, 7, 1), date(2026, 9, 30))

    bills = [_bill(1, [
        {"amount": 100.00, "tax_id": None, "booking_account_id": 100},
    ])]
    aggregate_bill_lines(bills, taxes, accounts, report)

    assert report.bills_skipped == 1
    assert any("MwSt-Code" in w for w in report.warnings)


def test_aggregate_warns_on_unknown_tax_id():
    taxes, accounts = _setup_caches()
    report = VatReport(2026, 3, date(2026, 7, 1), date(2026, 9, 30))

    bills = [_bill(1, [
        {"amount": 100.00, "tax_id": 999, "booking_account_id": 100},
    ])]
    aggregate_bill_lines(bills, taxes, accounts, report)

    assert any("unbekannter Tax-ID" in w for w in report.warnings)


def test_aggregate_skips_empty_bill():
    taxes, accounts = _setup_caches()
    report = VatReport(2026, 3, date(2026, 7, 1), date(2026, 9, 30))

    bills = [_bill(1, [])]
    aggregate_bill_lines(bills, taxes, accounts, report)

    assert report.bills_skipped == 1
    assert report.bills_processed == 0


def test_aggregate_multiple_lines_same_tax_combine():
    """Mehrere Lines mit gleichem Tax + gleicher Konto-Klasse summieren."""
    taxes, accounts = _setup_caches()
    report = VatReport(2026, 3, date(2026, 7, 1), date(2026, 9, 30))

    bills = [_bill(1, [
        {"amount": 108.10, "tax_id": 1, "booking_account_id": 100},
        {"amount": 54.05, "tax_id": 1, "booking_account_id": 100},  # gleicher account_class
    ])]
    aggregate_bill_lines(bills, taxes, accounts, report)

    assert len(report.lines) == 1
    line = list(report.lines.values())[0]
    assert line.line_count == 2
    assert round(line.total_gross, 2) == 162.15


def test_current_and_previous_quarter():
    y, q = current_quarter()
    assert 1 <= q <= 4
    assert 2024 <= y <= 2099

    py, pq = previous_quarter()
    assert 1 <= pq <= 4
