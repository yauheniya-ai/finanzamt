"""
finanzamt.agents.rules
~~~~~~~~~~~~~~~~~~~~~~
Rule-based extraction from OCR text.

Runs before any LLM call and produces a partial result dict.
This dict is passed to Agent 1 as "hints" and also serves as the
final fallback if all agents fail.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..utils import DataExtractor


class RulesResult:
    __slots__ = (
        "counterparty_name", "receipt_date", "total_amount",
        "vat_percentage", "vat_amount", "items", "receipt_type",
    )

    def __init__(
        self,
        counterparty_name:  Optional[str],
        receipt_date:       Optional[str],
        total_amount:       Optional[float],
        vat_percentage:     Optional[float],
        vat_amount:         Optional[float],
        items:              list,
        receipt_type:       str,
    ) -> None:
        self.counterparty_name = counterparty_name
        self.receipt_date      = receipt_date
        self.total_amount      = total_amount
        self.vat_percentage    = vat_percentage
        self.vat_amount        = vat_amount
        self.items             = items
        self.receipt_type      = receipt_type

    def to_dict(self) -> dict:
        return {
            "receipt_type":            self.receipt_type,
            "counterparty_name":       self.counterparty_name,
            "counterparty_tax_number": None,
            "counterparty_vat_id":     None,
            "counterparty_address": {
                "street": None, "street_number": None,
                "postcode": None, "city": None, "country": None,
            },
            "receipt_number":  None,
            "receipt_date":    self.receipt_date,
            "total_amount":    self.total_amount,
            "vat_percentage":  self.vat_percentage,
            "vat_amount":      self.vat_amount,
            "category":        "other",
            "items":           self.items,
        }


def run_rules(
    text:         str,
    receipt_type: str = "purchase",
    debug_dir:    Optional[Path] = None,
) -> RulesResult:
    """Run all rule-based extractors. Saves full output to debug_dir if given."""
    extractor = DataExtractor()

    dt      = extractor.extract_date(text)
    amounts = extractor.extract_amounts(text)
    vat     = extractor.extract_vat_info(text)
    name    = extractor.extract_company_name(text)
    items   = extractor.extract_items(text)

    result = RulesResult(
        counterparty_name = name,
        receipt_date      = dt.strftime("%Y-%m-%d") if dt else None,
        total_amount      = float(amounts["total"]) if amounts.get("total") else None,
        vat_percentage    = float(vat["vat_percentage"]) if vat.get("vat_percentage") else None,
        vat_amount        = float(vat["vat_amount"]) if vat.get("vat_amount") else None,
        items             = items,
        receipt_type      = receipt_type,
    )

    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        # Input: the OCR text fed into rules
        (debug_dir / "00_rules_input.txt").write_text(text, encoding="utf-8")
        # Output: complete rules result as JSON
        (debug_dir / "00_rules_output.json").write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return result


__all__ = ["run_rules", "RulesResult"]