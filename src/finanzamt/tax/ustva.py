"""
finanzamt.tax.ustva
~~~~~~~~~~~~~~~~~~~
Umsatzsteuer-Voranmeldung (UStVA) — German VAT pre-return.

VAT flow
--------
Purchase invoices (Eingangsrechnung)
    You paid a vendor.  Their VAT charge = your Vorsteuer (input tax).
    You reclaim this from the Finanzamt.

Sales invoices (Ausgangsrechnung)
    You invoiced a client.  You charged VAT = Umsatzsteuer (output tax).
    You remit this to the Finanzamt.

Net UStVA liability = output_tax − input_tax
  > 0  → you owe the state
  < 0  → state owes you a refund (Erstattung)
  = 0  → break-even

Usage::

    from finanzamt.storage import get_repository
    from finanzamt.tax.ustva import generate_ustva

    with get_repository() as repo:
        receipts = repo.find_by_period(date(2024,1,1), date(2024,3,31))
    report = generate_ustva(receipts, date(2024,1,1), date(2024,3,31))
    print(report.summary())
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable

from ..models import ReceiptData


_TWO = Decimal("0.01")


def _r(d: Decimal) -> Decimal:
    return d.quantize(_TWO, rounding=ROUND_HALF_UP)


def _to_date(dt: date | datetime) -> date:
    return dt.date() if isinstance(dt, datetime) else dt


# ---------------------------------------------------------------------------
# Per-rate line
# ---------------------------------------------------------------------------

@dataclass
class USTVALineItem:
    """Aggregated figures for one VAT rate, split by receipt type."""

    vat_rate:              Decimal
    # Purchase side (Vorsteuer — input tax you reclaim)
    purchase_net:          Decimal = field(default_factory=Decimal)
    purchase_vat:          Decimal = field(default_factory=Decimal)
    purchase_count:        int = 0
    # Sale side (Umsatzsteuer — output tax you remit)
    sale_net:              Decimal = field(default_factory=Decimal)
    sale_vat:              Decimal = field(default_factory=Decimal)
    sale_count:            int = 0

    @property
    def net_liability(self) -> Decimal:
        """Output VAT − input VAT for this rate. Positive = you owe."""
        return self.sale_vat - self.purchase_vat

    def to_dict(self) -> dict:
        return {
            "vat_rate":       str(self.vat_rate),
            "purchase_net":   str(self.purchase_net),
            "purchase_vat":   str(self.purchase_vat),
            "purchase_count": self.purchase_count,
            "sale_net":       str(self.sale_net),
            "sale_vat":       str(self.sale_vat),
            "sale_count":     self.sale_count,
            "net_liability":  str(self.net_liability),
        }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class USTVAReport:
    """
    UStVA summary for a reporting period.

    ``net_liability > 0``  → you owe the Finanzamt
    ``net_liability < 0``  → the Finanzamt owes you (Erstattung)
    """

    period_start:   date
    period_end:     date
    lines:          dict[str, USTVALineItem] = field(default_factory=dict)
    skipped_count:  int = 0

    # ------------------------------------------------------------------
    # Aggregated totals
    # ------------------------------------------------------------------

    @property
    def total_input_vat(self) -> Decimal:
        """Total Vorsteuer across all rates (from purchases)."""
        return sum((ln.purchase_vat for ln in self.lines.values()), Decimal("0"))

    @property
    def total_output_vat(self) -> Decimal:
        """Total Umsatzsteuer across all rates (from sales)."""
        return sum((ln.sale_vat for ln in self.lines.values()), Decimal("0"))

    @property
    def net_liability(self) -> Decimal:
        """output − input. Positive = you owe; negative = refund."""
        return self.total_output_vat - self.total_input_vat

    @property
    def total_purchase_net(self) -> Decimal:
        return sum((ln.purchase_net for ln in self.lines.values()), Decimal("0"))

    @property
    def total_sale_net(self) -> Decimal:
        return sum((ln.sale_net for ln in self.lines.values()), Decimal("0"))

    @property
    def total_receipts(self) -> int:
        return sum(ln.purchase_count + ln.sale_count for ln in self.lines.values())

    # Convenience accessors
    @property
    def line_19(self) -> USTVALineItem | None:
        return self.lines.get("19")

    @property
    def line_7(self) -> USTVALineItem | None:
        return self.lines.get("7")

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "period_start":      self.period_start.isoformat(),
            "period_end":        self.period_end.isoformat(),
            "total_receipts":    self.total_receipts,
            "skipped_count":     self.skipped_count,
            "total_purchase_net": str(self.total_purchase_net),
            "total_input_vat":   str(self.total_input_vat),
            "total_sale_net":    str(self.total_sale_net),
            "total_output_vat":  str(self.total_output_vat),
            "net_liability":     str(self.net_liability),
            "lines":             {k: v.to_dict() for k, v in sorted(self.lines.items())},
        }

    def to_json(self, path: str | Path | None = None) -> str:
        raw = json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
        if path:
            Path(path).write_text(raw, encoding="utf-8")
        return raw

    def summary(self) -> str:
        W = 52
        div  = "─" * W
        hdiv = "═" * W

        def owe_str() -> str:
            if self.net_liability > 0:
                return f"{self.net_liability:>10.2f} EUR  ← you owe the Finanzamt"
            elif self.net_liability < 0:
                return f"{abs(self.net_liability):>10.2f} EUR  ← Finanzamt owes you (Erstattung)"
            return "             0.00 EUR  (break-even)"

        lines = [
            "=" * W,
            f"  UStVA — {self.period_start} bis {self.period_end}",
            "=" * W,
            f"  Belege gesamt       : {self.total_receipts}",
            f"  Übersprungen        : {self.skipped_count}",
        ]

        if self.lines:
            lines.append(div)
            for rate_key, ln in sorted(self.lines.items()):
                lines += [
                    f"  USt-Satz {ln.vat_rate} %",
                    f"    Einkauf (Vorsteuer)",
                    f"      Nettobetrag    : {ln.purchase_net:>10.2f} EUR  ({ln.purchase_count} Belege)",
                    f"      Vorsteuer      : {ln.purchase_vat:>10.2f} EUR",
                    f"    Verkauf (Umsatzsteuer)",
                    f"      Nettobetrag    : {ln.sale_net:>10.2f} EUR  ({ln.sale_count} Belege)",
                    f"      Umsatzsteuer   : {ln.sale_vat:>10.2f} EUR",
                    f"      Saldo          : {ln.net_liability:>+10.2f} EUR",
                ]

        lines += [
            hdiv,
            f"  Gesamt Vorsteuer    : {self.total_input_vat:>10.2f} EUR",
            f"  Gesamt Umsatzsteuer : {self.total_output_vat:>10.2f} EUR",
            hdiv,
            f"  Zahllast / Erstatt. : {owe_str()}",
            "=" * W,
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def generate_ustva(
    receipts: Iterable[ReceiptData],
    period_start: date,
    period_end: date,
) -> USTVAReport:
    """
    Compute the UStVA figures from an iterable of receipts.

    Skips receipts that:
    - have no ``receipt_date``
    - fall outside the period
    - have no ``vat_amount`` or ``vat_amount <= 0``
    """
    report = USTVAReport(period_start=period_start, period_end=period_end)
    start = _to_date(period_start)
    end   = _to_date(period_end)

    for r in receipts:
        if r.receipt_date is None:
            report.skipped_count += 1
            continue
        if not (start <= _to_date(r.receipt_date) <= end):
            report.skipped_count += 1
            continue
        if not r.vat_amount or r.vat_amount <= 0:
            report.skipped_count += 1
            continue

        # Rate key
        rate_key = str(r.vat_percentage.normalize()) if r.vat_percentage else "unknown"
        if rate_key not in report.lines:
            report.lines[rate_key] = USTVALineItem(
                vat_rate=r.vat_percentage.normalize() if r.vat_percentage else Decimal("0")
            )

        ln  = report.lines[rate_key]
        vat = _r(r.vat_amount)
        net = _r(r.net_amount or Decimal("0"))

        if r.is_purchase:
            ln.purchase_vat += vat
            ln.purchase_net += net
            ln.purchase_count += 1
        else:  # sale
            ln.sale_vat += vat
            ln.sale_net += net
            ln.sale_count += 1

    # Final rounding pass
    for ln in report.lines.values():
        ln.purchase_vat = _r(ln.purchase_vat)
        ln.purchase_net = _r(ln.purchase_net)
        ln.sale_vat     = _r(ln.sale_vat)
        ln.sale_net     = _r(ln.sale_net)

    return report