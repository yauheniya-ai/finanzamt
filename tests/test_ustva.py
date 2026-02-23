"""
tests/test_ustva.py
~~~~~~~~~~~~~~~~~~~~
Tests for finanzamt.tax.ustva — generate_ustva, USTVAReport, USTVALineItem.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

import pytest

from finanzamt.models import ReceiptCategory, ReceiptData
from finanzamt.tax.ustva import USTVALineItem, USTVAReport, generate_ustva


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _receipt(
    *,
    receipt_date: datetime | None = datetime(2024, 2, 14),
    total_amount: str | None = "119.00",
    vat_percentage: str | None = "19",
    vat_amount: str | None = "19.00",
    category: str = "software",
) -> ReceiptData:
    return ReceiptData(
        vendor="Test GmbH",
        receipt_date=receipt_date,
        total_amount=Decimal(total_amount) if total_amount else None,
        vat_percentage=Decimal(vat_percentage) if vat_percentage else None,
        vat_amount=Decimal(vat_amount) if vat_amount else None,
        category=ReceiptCategory(category),
    )


Q1_START = date(2024, 1, 1)
Q1_END   = date(2024, 3, 31)


# ---------------------------------------------------------------------------
# generate_ustva — basic correctness
# ---------------------------------------------------------------------------

class TestGenerateUstva:
    def test_empty_input_returns_empty_report(self):
        report = generate_ustva([], Q1_START, Q1_END)
        assert report.total_vat   == Decimal("0")
        assert report.total_net   == Decimal("0")
        assert report.total_gross == Decimal("0")
        assert report.lines == {}

    def test_single_receipt_19pct(self):
        receipts = [_receipt(total_amount="119.00", vat_amount="19.00", vat_percentage="19")]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert "19" in report.lines
        assert report.lines["19"].vat_amount  == Decimal("19.00")
        assert report.lines["19"].net_amount  == Decimal("100.00")
        assert report.lines["19"].receipt_count == 1

    def test_single_receipt_7pct(self):
        receipts = [_receipt(total_amount="107.00", vat_amount="7.00", vat_percentage="7")]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert "7" in report.lines
        assert report.lines["7"].vat_amount == Decimal("7.00")

    def test_mixed_rates_grouped_separately(self):
        receipts = [
            _receipt(total_amount="119.00", vat_amount="19.00", vat_percentage="19"),
            _receipt(total_amount="107.00", vat_amount="7.00",  vat_percentage="7"),
        ]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert "19" in report.lines
        assert "7"  in report.lines
        assert report.lines["19"].receipt_count == 1
        assert report.lines["7"].receipt_count  == 1

    def test_multiple_receipts_same_rate_accumulated(self):
        receipts = [
            _receipt(total_amount="119.00", vat_amount="19.00", vat_percentage="19"),
            _receipt(total_amount="238.00", vat_amount="38.00", vat_percentage="19"),
        ]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert report.lines["19"].vat_amount  == Decimal("57.00")
        assert report.lines["19"].net_amount  == Decimal("300.00")
        assert report.lines["19"].receipt_count == 2

    def test_total_vat_sums_all_lines(self):
        receipts = [
            _receipt(total_amount="119.00", vat_amount="19.00", vat_percentage="19"),
            _receipt(total_amount="107.00", vat_amount="7.00",  vat_percentage="7"),
        ]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert report.total_vat == Decimal("26.00")

    def test_total_gross_equals_net_plus_vat(self):
        receipts = [_receipt(total_amount="119.00", vat_amount="19.00", vat_percentage="19")]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert report.total_gross == report.total_net + report.total_vat


# ---------------------------------------------------------------------------
# generate_ustva — skipping logic
# ---------------------------------------------------------------------------

class TestSkipping:
    def test_skips_receipt_without_date(self):
        r = _receipt(receipt_date=None)
        report = generate_ustva([r], Q1_START, Q1_END)
        assert report.skipped_count == 1
        assert report.total_vat == Decimal("0")

    def test_skips_receipt_outside_period(self):
        r = _receipt(receipt_date=datetime(2024, 12, 1))
        report = generate_ustva([r], Q1_START, Q1_END)
        assert report.skipped_count == 1
        assert report.total_vat == Decimal("0")

    def test_skips_receipt_with_zero_vat(self):
        r = _receipt(vat_amount="0.00")
        report = generate_ustva([r], Q1_START, Q1_END)
        assert report.skipped_count == 1

    def test_skips_receipt_with_none_vat(self):
        r = _receipt(vat_amount=None)
        report = generate_ustva([r], Q1_START, Q1_END)
        assert report.skipped_count == 1

    def test_skipped_and_valid_counted_separately(self):
        receipts = [
            _receipt(receipt_date=None),                          # skipped
            _receipt(receipt_date=datetime(2023, 6, 1)),          # outside period
            _receipt(receipt_date=datetime(2024, 2, 1)),          # valid
        ]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert report.skipped_count == 2
        assert report.total_receipts == 1

    def test_period_boundary_inclusive(self):
        receipts = [
            _receipt(receipt_date=datetime(2024, 1, 1)),   # first day
            _receipt(receipt_date=datetime(2024, 3, 31)),  # last day
        ]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert report.skipped_count == 0
        assert report.total_receipts == 2


# ---------------------------------------------------------------------------
# generate_ustva — datetime vs date regression
# ---------------------------------------------------------------------------

class TestDateHandling:
    def test_datetime_receipt_date_does_not_raise(self):
        """Regression: datetime <= date comparison raised TypeError."""
        r = _receipt(receipt_date=datetime(2024, 2, 15, 14, 30))
        report = generate_ustva([r], Q1_START, Q1_END)
        assert report.total_receipts == 1

    def test_date_bounds_accepted(self):
        r = _receipt(receipt_date=datetime(2024, 2, 15))
        report = generate_ustva([r], date(2024, 1, 1), date(2024, 3, 31))
        assert report.total_receipts == 1

    def test_datetime_bounds_accepted(self):
        r = _receipt(receipt_date=datetime(2024, 2, 15))
        report = generate_ustva([r], datetime(2024, 1, 1), datetime(2024, 3, 31))
        assert report.total_receipts == 1


# ---------------------------------------------------------------------------
# USTVALineItem
# ---------------------------------------------------------------------------

class TestUSTVALineItem:
    def test_gross_amount_is_net_plus_vat(self):
        ln = USTVALineItem(
            vat_rate=Decimal("19"),
            net_amount=Decimal("100.00"),
            vat_amount=Decimal("19.00"),
        )
        assert ln.gross_amount == Decimal("119.00")

    def test_to_dict_keys(self):
        ln = USTVALineItem(
            vat_rate=Decimal("19"),
            net_amount=Decimal("100.00"),
            vat_amount=Decimal("19.00"),
            receipt_count=3,
        )
        d = ln.to_dict()
        assert set(d.keys()) == {"vat_rate", "net_amount", "vat_amount", "gross_amount", "receipt_count"}
        assert d["receipt_count"] == 3
        assert d["gross_amount"] == "119.00"


# ---------------------------------------------------------------------------
# USTVAReport
# ---------------------------------------------------------------------------

class TestUSTVAReport:
    def _report_with_lines(self) -> USTVAReport:
        report = USTVAReport(period_start=Q1_START, period_end=Q1_END)
        report.lines["19"] = USTVALineItem(
            vat_rate=Decimal("19"),
            net_amount=Decimal("200.00"),
            vat_amount=Decimal("38.00"),
            receipt_count=2,
        )
        report.lines["7"] = USTVALineItem(
            vat_rate=Decimal("7"),
            net_amount=Decimal("100.00"),
            vat_amount=Decimal("7.00"),
            receipt_count=1,
        )
        return report

    def test_total_net(self):
        assert self._report_with_lines().total_net == Decimal("300.00")

    def test_total_vat(self):
        assert self._report_with_lines().total_vat == Decimal("45.00")

    def test_total_gross(self):
        assert self._report_with_lines().total_gross == Decimal("345.00")

    def test_total_receipts(self):
        assert self._report_with_lines().total_receipts == 3

    def test_line_19_accessor(self):
        report = self._report_with_lines()
        assert report.line_19 is not None
        assert report.line_19.vat_rate == Decimal("19")

    def test_line_7_accessor(self):
        report = self._report_with_lines()
        assert report.line_7 is not None
        assert report.line_7.vat_rate == Decimal("7")

    def test_line_19_none_when_absent(self):
        report = USTVAReport(period_start=Q1_START, period_end=Q1_END)
        assert report.line_19 is None


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class TestExport:
    def test_to_dict_structure(self):
        receipts = [_receipt(total_amount="119.00", vat_amount="19.00", vat_percentage="19")]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        d = report.to_dict()
        assert d["period_start"] == "2024-01-01"
        assert d["period_end"]   == "2024-03-31"
        assert "total_vat"   in d
        assert "total_net"   in d
        assert "total_gross" in d
        assert "lines"       in d
        assert "19" in d["lines"]

    def test_to_json_is_valid_json(self):
        receipts = [_receipt()]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        raw = report.to_json()
        parsed = json.loads(raw)
        assert "period_start" in parsed

    def test_to_json_writes_file(self, tmp_path):
        receipts = [_receipt()]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        out = tmp_path / "ustva.json"
        report.to_json(out)
        assert out.exists()
        parsed = json.loads(out.read_text(encoding="utf-8"))
        assert parsed["period_start"] == "2024-01-01"

    def test_summary_contains_period(self):
        receipts = [_receipt()]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        summary = report.summary()
        assert "2024-01-01" in summary
        assert "2024-03-31" in summary

    def test_summary_contains_vat_rate(self):
        receipts = [_receipt(vat_percentage="19", vat_amount="19.00")]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert "19" in report.summary()

    def test_summary_contains_totals(self):
        receipts = [_receipt(total_amount="119.00", vat_amount="19.00", vat_percentage="19")]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        summary = report.summary()
        assert "19.00" in summary    # VAT amount
        assert "100.00" in summary   # net amount


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------

class TestRounding:
    def test_vat_amounts_rounded_to_two_decimal_places(self):
        receipts = [
            _receipt(total_amount="10.00", vat_amount="1.905", vat_percentage="19"),
        ]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        # 1.905 rounds to 1.91 (ROUND_HALF_UP)
        assert report.lines["19"].vat_amount == Decimal("1.91")

    def test_decimal_normalisation(self):
        """Decimal('19.0').normalize() == '19' — must map to same bucket as '19'."""
        receipts = [
            _receipt(vat_percentage="19.0", vat_amount="19.00"),
            _receipt(vat_percentage="19",   vat_amount="19.00"),
        ]
        report = generate_ustva(receipts, Q1_START, Q1_END)
        assert len(report.lines) == 1   # both map to "19", not "19" + "19.0"
        assert report.lines["19"].receipt_count == 2
