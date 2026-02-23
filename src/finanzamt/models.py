"""
finanzamt.models
~~~~~~~~~~~~~~~~
Data models for extracted receipt information.

Key design decisions
--------------------
* Receipt ID is a SHA-256 hash of the normalised raw OCR text.
  Identical content → identical ID → automatic duplicate detection.

* ``ReceiptType`` distinguishes purchase invoices (Eingangsrechnung —
  input tax you reclaim) from sales invoices (Ausgangsrechnung —
  output tax you remit).

* ``Counterparty`` replaces the old ``vendor`` field and covers both
  vendors (on purchase invoices) and clients (on sales invoices).

* ``ReceiptCategory`` remains a thin string wrapper keyed to the same
  list the LLM is prompted with — single source of truth.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from .prompts import RECEIPT_CATEGORIES


# ---------------------------------------------------------------------------
# ReceiptCategory  (unchanged)
# ---------------------------------------------------------------------------

class ReceiptCategory(str):
    """
    A validated receipt category string.

    Unknown values are silently normalised to ``"other"`` so that LLM
    hallucinations never break model construction.
    """

    VALID: frozenset = frozenset(RECEIPT_CATEGORIES)

    def __new__(cls, value: str = "other") -> "ReceiptCategory":
        normalised = str(value).strip().lower()
        if normalised not in RECEIPT_CATEGORIES:
            normalised = "other"
        return super().__new__(cls, normalised)

    @classmethod
    def other(cls) -> "ReceiptCategory":
        return cls("other")


# ---------------------------------------------------------------------------
# ReceiptType
# ---------------------------------------------------------------------------

class ReceiptType(str):
    """
    Whether this is a purchase or a sales invoice.

    ``"purchase"``  — Eingangsrechnung. You paid a vendor.
                      VAT = Vorsteuer (input tax) → you reclaim it.

    ``"sale"``      — Ausgangsrechnung. A client paid you.
                      VAT = Umsatzsteuer (output tax) → you remit it to the state.
    """

    _VALID = {"purchase", "sale"}

    def __new__(cls, value: str = "purchase") -> "ReceiptType":
        normalised = str(value).strip().lower()
        if normalised not in cls._VALID:
            normalised = "purchase"
        return super().__new__(cls, normalised)

    @classmethod
    def purchase(cls) -> "ReceiptType":
        return cls("purchase")

    @classmethod
    def sale(cls) -> "ReceiptType":
        return cls("sale")


# ---------------------------------------------------------------------------
# Address
# ---------------------------------------------------------------------------

@dataclass
class Address:
    """
    Structured postal address.

    All fields are optional because OCR and LLM extraction may not find them.
    """

    street:        Optional[str] = None
    street_number: Optional[str] = None
    postcode:      Optional[str] = None
    city:          Optional[str] = None
    country:       Optional[str] = None

    def __str__(self) -> str:
        """Return a compact one-line representation for display."""
        parts = []
        if self.street or self.street_number:
            parts.append(f"{self.street or ''} {self.street_number or ''}".strip())
        if self.postcode or self.city:
            parts.append(f"{self.postcode or ''} {self.city or ''}".strip())
        if self.country:
            parts.append(self.country)
        return ", ".join(p for p in parts if p)

    def to_dict(self) -> dict:
        return {
            "street":        self.street,
            "street_number": self.street_number,
            "postcode":      self.postcode,
            "city":          self.city,
            "country":       self.country,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Address":
        return cls(
            street=        d.get("street"),
            street_number= d.get("street_number"),
            postcode=      d.get("postcode"),
            city=          d.get("city"),
            country=       d.get("country"),
        )

    @classmethod
    def empty(cls) -> "Address":
        return cls()


# ---------------------------------------------------------------------------
# Counterparty
# ---------------------------------------------------------------------------

@dataclass
class Counterparty:
    """
    The other party on a receipt — a vendor (on purchases) or a client (on sales).

    ``id`` is a UUID assigned by the database layer.  Two counterparties are
    considered the same entity if their ``vat_id`` matches, or failing that,
    if their ``name`` matches case-insensitively.
    """

    id:          str = field(default_factory=lambda: str(uuid.uuid4()))
    name:        Optional[str] = None
    address:     Address = field(default_factory=Address.empty)
    tax_number:  Optional[str] = None   # German Steuernummer
    vat_id:      Optional[str] = None   # EU USt-IdNr e.g. DE123456789

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "name":         self.name,
            "address":      self.address.to_dict(),
            "tax_number":   self.tax_number,
            "vat_id":       self.vat_id,
        }


# ---------------------------------------------------------------------------
# ReceiptItem  (unchanged structure)
# ---------------------------------------------------------------------------

@dataclass
class ReceiptItem:
    """A single line item within a receipt."""

    description: str = ""
    quantity:    Optional[Decimal] = None
    unit_price:  Optional[Decimal] = None
    total_price: Optional[Decimal] = None
    category:    ReceiptCategory = field(default_factory=ReceiptCategory.other)
    vat_rate:    Optional[Decimal] = None

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "quantity":    float(self.quantity)    if self.quantity    is not None else None,
            "unit_price":  float(self.unit_price)  if self.unit_price  is not None else None,
            "total_price": float(self.total_price) if self.total_price is not None else None,
            "category":    str(self.category),
            "vat_rate":    float(self.vat_rate)    if self.vat_rate    is not None else None,
        }


# ---------------------------------------------------------------------------
# ReceiptData
# ---------------------------------------------------------------------------

def _content_hash(raw_text: str) -> str:
    """SHA-256 of normalised OCR text — used as the stable receipt ID."""
    normalised = "\n".join(line.strip() for line in raw_text.splitlines()).strip()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


@dataclass
class ReceiptData:
    """
    Structured data extracted from a single receipt or invoice.

    The ``id`` is derived from the content hash of ``raw_text`` — pass
    ``raw_text`` first so the default factory can compute it.
    Alternatively, set ``id`` explicitly (e.g. when loading from DB).

    ``receipt_type`` controls how VAT is treated for tax purposes:
    - ``"purchase"``  → Vorsteuer  (input tax,  you reclaim)
    - ``"sale"``      → Umsatzsteuer (output tax, you remit)
    """

    raw_text:         str = ""
    id:               str = field(init=False)   # set in __post_init__

    receipt_type:     ReceiptType = field(default_factory=ReceiptType.purchase)
    counterparty:     Optional[Counterparty] = None

    receipt_number:   Optional[str] = None
    receipt_date:     Optional[datetime] = None
    total_amount:     Optional[Decimal] = None
    vat_percentage:   Optional[Decimal] = None
    vat_amount:       Optional[Decimal] = None
    category:         ReceiptCategory = field(default_factory=ReceiptCategory.other)
    items:            List[ReceiptItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.id = _content_hash(self.raw_text)

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    @property
    def vendor(self) -> Optional[str]:
        """Backward-compatible alias for counterparty.name."""
        return self.counterparty.name if self.counterparty else None

    @property
    def net_amount(self) -> Optional[Decimal]:
        if self.total_amount is not None and self.vat_amount is not None:
            return self.total_amount - self.vat_amount
        return None

    @property
    def is_purchase(self) -> bool:
        return str(self.receipt_type) == "purchase"

    @property
    def is_sale(self) -> bool:
        return str(self.receipt_type) == "sale"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> bool:
        if self.receipt_date and self.receipt_date > datetime.now():
            return False
        if self.total_amount is not None and self.total_amount <= 0:
            return False
        if self.vat_percentage is not None and not (0 <= self.vat_percentage <= 100):
            return False
        if (
            self.total_amount is not None
            and self.vat_amount is not None
            and self.vat_amount > self.total_amount
        ):
            return False
        return True

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "id":             self.id,
            "receipt_type":   str(self.receipt_type),
            "vendor":         self.vendor,  # convenience alias for counterparty.name
            "counterparty":   self.counterparty.to_dict() if self.counterparty else None,
            "receipt_number": self.receipt_number,
            "receipt_date":   self.receipt_date.date().isoformat() if self.receipt_date else None,
            "total_amount":   float(self.total_amount)   if self.total_amount   is not None else None,
            "vat_percentage": float(self.vat_percentage) if self.vat_percentage is not None else None,
            "vat_amount":     float(self.vat_amount)     if self.vat_amount     is not None else None,
            "net_amount":     float(self.net_amount)     if self.net_amount     is not None else None,
            "category":       str(self.category),
            "items":          [item.to_dict() for item in self.items],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# ExtractionResult
# ---------------------------------------------------------------------------

@dataclass
class ExtractionResult:
    """
    Top-level result returned by ``FinanceAgent.process_receipt()``.

    Always check ``success`` before accessing ``data``.
    When ``duplicate`` is True, the receipt was not re-saved — see
    ``existing_id`` for the ID of the original.
    """

    success:         bool
    data:            Optional[ReceiptData] = None
    error_message:   Optional[str] = None
    processing_time: Optional[float] = None
    duplicate:       bool = False
    existing_id:     Optional[str] = None   # set when duplicate=True

    def to_dict(self) -> dict:
        return {
            "success":         self.success,
            "duplicate":       self.duplicate,
            "existing_id":     self.existing_id,
            "data":            self.data.to_dict() if self.data else None,
            "error_message":   self.error_message,
            "processing_time": round(self.processing_time, 3) if self.processing_time else None,
        }