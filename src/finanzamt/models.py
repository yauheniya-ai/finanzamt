"""
finanzamt.models
~~~~~~~~~~~~~~~~
Data models for extracted receipt information.

Design decisions
----------------
* ``ReceiptCategory`` is a thin wrapper around the canonical string list
  defined in ``finanzamt.prompts``.  There is intentionally **no separate
  Enum** — keeping one source of truth prevents the LLM prompt and the
  model from drifting out of sync (which was the root cause of every
  category silently falling back to "other").

* Field names match the keys returned by the LLM extraction prompt
  (``vendor``, ``total_amount``, ``vat_amount``, …) so that the agent can
  pass the parsed JSON dict directly without a renaming step.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

# Single source of truth — the same list the LLM is prompted with.
from .prompts import RECEIPT_CATEGORIES


# ---------------------------------------------------------------------------
# Category helper
# ---------------------------------------------------------------------------

class ReceiptCategory(str):
    """
    A validated receipt category string.

    Behaves exactly like ``str`` so it serialises transparently to JSON.
    Falls back to ``"other"`` for unknown values rather than raising, since
    OCR noise can produce unexpected strings.
    """

    VALID: frozenset[str] = frozenset(RECEIPT_CATEGORIES)

    def __new__(cls, value: str) -> "ReceiptCategory":
        normalised = value.strip().lower() if value else "other"
        if normalised not in cls.VALID:
            normalised = "other"
        return super().__new__(cls, normalised)

    @classmethod
    def other(cls) -> "ReceiptCategory":
        return cls("other")


# ---------------------------------------------------------------------------
# Receipt item
# ---------------------------------------------------------------------------

@dataclass
class ReceiptItem:
    """A single line item on a receipt."""

    description: str
    total_price: Optional[Decimal] = None
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    category: ReceiptCategory = field(default_factory=ReceiptCategory.other)
    vat_rate: Optional[Decimal] = None

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "quantity":    float(self.quantity)   if self.quantity   is not None else None,
            "unit_price":  float(self.unit_price) if self.unit_price is not None else None,
            "total_price": float(self.total_price) if self.total_price is not None else None,
            "category":    str(self.category),
            "vat_rate":    float(self.vat_rate)   if self.vat_rate   is not None else None,
        }


# ---------------------------------------------------------------------------
# Receipt header
# ---------------------------------------------------------------------------

@dataclass
class ReceiptData:
    """
    Structured data extracted from a single receipt.

    Field names deliberately match the JSON keys produced by the LLM
    extraction prompt so the agent can map results without an explicit
    rename step.
    """

    vendor: Optional[str] = None
    vendor_address: Optional[str] = None
    receipt_number: Optional[str] = None
    receipt_date: Optional[datetime] = None      # parsed from "YYYY-MM-DD"
    total_amount: Optional[Decimal] = None
    vat_percentage: Optional[Decimal] = None
    vat_amount: Optional[Decimal] = None
    category: ReceiptCategory = field(default_factory=ReceiptCategory.other)
    raw_text: str = ""
    items: List[ReceiptItem] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    @property
    def net_amount(self) -> Optional[Decimal]:
        """Total minus VAT, or None if either value is missing."""
        if self.total_amount is not None and self.vat_amount is not None:
            return self.total_amount - self.vat_amount
        return None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> bool:
        """
        Run basic business-logic sanity checks.

        Returns True when data looks plausible; False otherwise.
        Raises nothing — callers decide how to handle invalid data.
        """
        if self.receipt_date and self.receipt_date > datetime.now():
            return False  # receipt dated in the future
        if self.total_amount is not None and self.total_amount <= 0:
            return False  # negative or zero total
        if self.vat_percentage is not None and not (0 <= self.vat_percentage <= 100):
            return False  # VAT rate out of range
        if (
            self.total_amount is not None
            and self.vat_amount is not None
            and self.vat_amount > self.total_amount
        ):
            return False  # VAT cannot exceed the total
        return True

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "vendor":          self.vendor,
            "vendor_address":  self.vendor_address,
            "receipt_number":  self.receipt_number,
            "receipt_date":    self.receipt_date.date().isoformat() if self.receipt_date else None,
            "total_amount":    float(self.total_amount)    if self.total_amount    is not None else None,
            "vat_percentage":  float(self.vat_percentage)  if self.vat_percentage  is not None else None,
            "vat_amount":      float(self.vat_amount)      if self.vat_amount      is not None else None,
            "net_amount":      float(self.net_amount)      if self.net_amount      is not None else None,
            "category":        str(self.category),
            "items":           [item.to_dict() for item in self.items],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Extraction result wrapper
# ---------------------------------------------------------------------------

@dataclass
class ExtractionResult:
    """
    Top-level result returned by ``FinanceAgent.process_receipt()``.

    Always check ``success`` before accessing ``data``.
    """

    success: bool
    data: Optional[ReceiptData] = None
    error_message: Optional[str] = None
    processing_time: Optional[float] = None   # seconds

    def to_dict(self) -> dict:
        return {
            "success":         self.success,
            "data":            self.data.to_dict() if self.data else None,
            "error_message":   self.error_message,
            "processing_time": round(self.processing_time, 3) if self.processing_time else None,
        }