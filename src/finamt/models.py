"""
finamt.models
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
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List

from .agents.prompts import RECEIPT_CATEGORIES


# ---------------------------------------------------------------------------
# Posting helpers
# ---------------------------------------------------------------------------

_TWO = Decimal("0.01")


def _r2(d: Decimal) -> Decimal:
    """Round to 2 decimal places (half-up)."""
    return d.quantize(_TWO, rounding=ROUND_HALF_UP)


class PostingDirection(str):
    """
    Direction of a double-entry posting — ``'debit'`` or ``'credit'``.
    """

    _VALID = {"debit", "credit"}

    def __new__(cls, value: str) -> "PostingDirection":
        v = str(value).strip().lower()
        if v not in cls._VALID:
            raise ValueError(f"PostingDirection must be 'debit' or 'credit', got {value!r}")
        return super().__new__(cls, v)


class PostingType(str):
    """
    Account type for a double-entry posting.

    ``expense``             — Betriebsausgabe
    ``input_vat``           — Vorsteuer
    ``accounts_payable``    — Verbindlichkeiten Lieferanten
    ``revenue``             — Betriebseinnahme
    ``output_vat``          — Umsatzsteuer
    ``accounts_receivable`` — Forderungen Kunden
    ``private_withdrawal``  — Privatentnahme / geldwerter Vorteil
    """

    _VALID = {
        "expense",
        "input_vat",
        "accounts_payable",
        "revenue",
        "output_vat",
        "accounts_receivable",
        "private_withdrawal",
    }

    def __new__(cls, value: str) -> "PostingType":
        v = str(value).strip().lower()
        if v not in cls._VALID:
            raise ValueError(f"Unknown PostingType: {value!r}")
        return super().__new__(cls, v)


@dataclass
class Posting:
    """
    A single double-entry journal posting generated from a receipt.

    For each receipt ``ReceiptData.generate_postings()`` returns a balanced
    list of debits and credits.  When ``private_use_share > 0`` the list
    includes correction postings that isolate the non-deductible private
    portion so that:

    * VAT is only claimed on the business portion.
    * The full gross amount is still preserved as accounts payable.
    * A private withdrawal posting captures the owner's benefit in kind.
    * An EÜR can be derived by aggregating only the *net* expense/revenue
      postings (after corrections).

    Fields
    ------
    receipt_id   : back-reference to the parent receipt
    posting_type : account type (expense, input_vat, …)
    direction    : 'debit' or 'credit'
    amount       : always positive
    description  : human-readable general-ledger label
    """

    receipt_id:   str
    posting_type: PostingType
    direction:    PostingDirection
    amount:       Decimal
    description:  str = ""

    def to_dict(self) -> dict:
        return {
            "receipt_id":   self.receipt_id,
            "posting_type": str(self.posting_type),
            "direction":    str(self.direction),
            "amount":       float(self.amount),
            "description":  self.description,
        }


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
    ``address_supplement`` captures a secondary address line (e.g. building name,
    campus, suite) that appears separately from the street and number.
    """

    street_and_number:  Optional[str] = None
    address_supplement: Optional[str] = None
    postcode:           Optional[str] = None
    city:               Optional[str] = None
    state:              Optional[str] = None
    country:            Optional[str] = None

    def __str__(self) -> str:
        """Return a compact one-line representation for display."""
        parts = []
        if self.street_and_number:
            parts.append(self.street_and_number)
        if self.address_supplement:
            parts.append(self.address_supplement)
        if self.postcode or self.city:
            parts.append(f"{self.postcode or ''} {self.city or ''}".strip())
        if self.state:
            parts.append(self.state)
        if self.country:
            parts.append(self.country)
        return ", ".join(p for p in parts if p)

    def to_dict(self) -> dict:
        return {
            "street_and_number":  self.street_and_number,
            "address_supplement": self.address_supplement,
            "postcode":           self.postcode,
            "city":               self.city,
            "state":              self.state,
            "country":            self.country,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Address":
        return cls(
            street_and_number=  d.get("street_and_number"),
            address_supplement= d.get("address_supplement"),
            postcode=           d.get("postcode"),
            city=               d.get("city"),
            state=              d.get("state"),
            country=            d.get("country"),
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
    verified:    bool = False

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "name":         self.name,
            "address":      self.address.to_dict(),
            "tax_number":   self.tax_number,
            "vat_id":       self.vat_id,
            "verified":     self.verified,
        }


# ---------------------------------------------------------------------------
# ReceiptItem  (unchanged structure)
# ---------------------------------------------------------------------------

@dataclass
class ReceiptItem:
    """A single line item within a receipt."""

    description: str = ""
    position:    Optional[int] = None
    quantity:    Optional[Decimal] = None
    unit_price:  Optional[Decimal] = None
    total_price: Optional[Decimal] = None
    vat_rate:    Optional[Decimal] = None
    vat_amount:  Optional[Decimal] = None
    category:    ReceiptCategory = field(default_factory=ReceiptCategory.other)

    def to_dict(self) -> dict:
        return {
            "position":    self.position,
            "description": self.description,
            "quantity":    float(self.quantity)    if self.quantity    is not None else None,
            "unit_price":  float(self.unit_price)  if self.unit_price  is not None else None,
            "total_price": float(self.total_price) if self.total_price is not None else None,
            "vat_rate":    float(self.vat_rate)    if self.vat_rate    is not None else None,
            "vat_amount":  float(self.vat_amount)  if self.vat_amount  is not None else None,
            "category":    str(self.category),
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
    currency:         str = "EUR"
    category:         ReceiptCategory = field(default_factory=ReceiptCategory.other)
    subcategory:      Optional[str] = None
    description:      str = ""                # free-text notes / memo
    items:            List[ReceiptItem] = field(default_factory=list)
    vat_splits:       List[dict] = field(default_factory=list)
    # Populated by validate(); empty = clean, non-empty = user-visible warnings.
    # Receipts are always saved regardless — the user decides to correct or delete.
    validation_warnings: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Private-use handling
    # ------------------------------------------------------------------
    #
    # private_use_share — fraction of this receipt that is *non-business*
    # (0 = fully business, 1 = fully private).  Amounts (net, VAT, gross)
    # are always stored at face value; the private share is resolved via
    # ``generate_postings()`` so the full audit trail is preserved.
    private_use_share: Decimal = field(default_factory=lambda: Decimal("0"))

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
        # Correct gross-to-net: NETTO = BRUTTO ÷ (1 + MwSt./100)
        # This is the only correct formula when total_amount is a gross (VAT-inclusive) figure.
        if self.total_amount is not None and self.vat_percentage is not None:
            rate = self.vat_percentage / Decimal("100")
            return _r2(self.total_amount / (Decimal("1") + rate))
        # Fallback: if only the stored vat_amount is available, subtract directly
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
    # Private-use postings
    # ------------------------------------------------------------------

    def generate_postings(self) -> List["Posting"]:
        """
        Generate a balanced list of double-entry postings for this receipt.

        **Purchase** (``private_use_share = 0``):

        .. code-block:: text

            DEBIT  expense           net   — Betriebsausgabe (gesamt)
            DEBIT  input_vat         vat   — Vorsteuer (gesamt)
            CREDIT accounts_payable  gross — Verbindlichkeit Lieferant

        **Purchase** (``private_use_share = p > 0``) — additional corrections:

        .. code-block:: text

            CREDIT expense           net*p         — Privatanteil Korrektur (Netto)
            CREDIT input_vat         vat*p         — Privatanteil Vorsteuerkorrektur
            DEBIT  private_withdrawal gross*p      — Privatentnahme / geldwerter Vorteil

        Net effect: only ``net*(1-p)`` flows through the expense account and
        only ``vat*(1-p)`` remains as reclaimable input VAT.

        **Sale**:

        .. code-block:: text

            DEBIT  accounts_receivable  gross — Forderung Kunde
            CREDIT revenue              net   — Betriebseinnahme (netto)
            CREDIT output_vat           vat   — Umsatzsteuer

        Returns an empty list when amounts are not yet available.
        """
        if self.total_amount is None or self.net_amount is None:
            return []

        gross = _r2(self.total_amount)
        net   = _r2(self.net_amount)
        vat   = _r2(gross - net)   # derived from gross−net, consistent with net_amount formula
        p     = Decimal(str(self.private_use_share))
        rid   = self.id

        postings: List[Posting] = []

        if self.is_purchase:
            postings += [
                Posting(rid, PostingType("expense"),          PostingDirection("debit"),  net,   "Betriebsausgabe (gesamt)"),
                Posting(rid, PostingType("input_vat"),        PostingDirection("debit"),  vat,   "Vorsteuer (gesamt)"),
                Posting(rid, PostingType("accounts_payable"), PostingDirection("credit"), gross, "Verbindlichkeit Lieferant"),
            ]
            if p > Decimal("0"):
                priv_net   = _r2(net   * p)
                priv_vat   = _r2(vat   * p)
                priv_gross = _r2(gross * p)
                postings += [
                    Posting(rid, PostingType("expense"),            PostingDirection("credit"), priv_net,   "Privatanteil Korrektur (Netto)"),
                    Posting(rid, PostingType("input_vat"),          PostingDirection("credit"), priv_vat,   "Privatanteil Vorsteuerkorrektur"),
                    Posting(rid, PostingType("private_withdrawal"),  PostingDirection("debit"),  priv_gross, "Privatentnahme / geldwerter Vorteil"),
                ]
        else:  # sale
            postings += [
                Posting(rid, PostingType("accounts_receivable"), PostingDirection("debit"),  gross, "Forderung Kunde"),
                Posting(rid, PostingType("revenue"),             PostingDirection("credit"), net,   "Betriebseinnahme (netto)"),
                Posting(rid, PostingType("output_vat"),          PostingDirection("credit"), vat,   "Umsatzsteuer"),
            ]

        return postings

    @property
    def business_net(self) -> Optional[Decimal]:
        """Net amount attributable to the business (after private-use deduction)."""
        if self.net_amount is None:
            return None
        return _r2(self.net_amount * (Decimal("1") - Decimal(str(self.private_use_share))))

    @property
    def business_vat(self) -> Optional[Decimal]:
        """Reclaimable / remittable VAT for the business portion only."""
        if self.total_amount is None or self.net_amount is None:
            return None
        vat = _r2(self.total_amount - self.net_amount)  # consistent with net_amount formula
        return _r2(vat * (Decimal("1") - Decimal(str(self.private_use_share))))

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> bool:
        """
        Collect business-rule warnings into ``self.validation_warnings``.

        Returns True when there are no warnings (clean receipt).
        Returns False when at least one rule is violated.

        Regardless of the return value, receipts are *always* saved — the
        caller must not block on a False return.  Warnings are stored in the
        DB and shown to the user, who decides to correct or delete.
        """
        warnings: List[str] = []
        if self.receipt_date and self.receipt_date > datetime.now():
            warnings.append(f"Future date: {self.receipt_date.date().isoformat()}")
        if self.total_amount is not None and self.total_amount <= 0:
            warnings.append(f"Total amount must be positive (got {self.total_amount})")
        if self.vat_percentage is not None and not (0 <= self.vat_percentage <= 100):
            warnings.append(f"VAT percentage out of range: {self.vat_percentage}")
        if (
            self.total_amount is not None
            and self.vat_amount is not None
            and self.vat_amount > self.total_amount
        ):
            warnings.append(
                f"VAT amount ({self.vat_amount}) exceeds total ({self.total_amount})"
            )
        if not (Decimal("0") <= Decimal(str(self.private_use_share)) <= Decimal("1")):
            warnings.append(f"Private use share out of range: {self.private_use_share}")
        self.validation_warnings = warnings
        return len(warnings) == 0

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "receipt_type":     str(self.receipt_type),
            "vendor":           self.vendor,  # convenience alias for counterparty.name
            "counterparty":     self.counterparty.to_dict() if self.counterparty else None,
            "receipt_number":   self.receipt_number,
            "receipt_date":     self.receipt_date.date().isoformat() if self.receipt_date else None,
            "total_amount":     float(self.total_amount)     if self.total_amount     is not None else None,
            "vat_percentage":   float(self.vat_percentage)   if self.vat_percentage   is not None else None,
            "vat_amount":       float(self.vat_amount)       if self.vat_amount       is not None else None,
            "net_amount":       float(self.net_amount)       if self.net_amount       is not None else None,
            "private_use_share": float(self.private_use_share),
            "business_net":     float(self.business_net)     if self.business_net     is not None else None,
            "business_vat":     float(self.business_vat)     if self.business_vat     is not None else None,
            "currency":         self.currency,
            "category":         str(self.category),
            "subcategory":      self.subcategory,
            "description":      self.description or None,
            "items":            [item.to_dict() for item in self.items],
            "vat_splits":       getattr(self, "vat_splits", []),
            "validation_warnings": getattr(self, "validation_warnings", []),
            "created_at":       getattr(self, "created_at", None),
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
    