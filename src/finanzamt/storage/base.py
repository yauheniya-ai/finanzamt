"""
finanzamt.storage.base
~~~~~~~~~~~~~~~~~~~~~~
Abstract repository interface.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable, Protocol, runtime_checkable

from ..models import Counterparty, ReceiptData


@runtime_checkable
class ReceiptRepository(Protocol):
    """Storage abstraction for receipt persistence."""

    def save(self, receipt: ReceiptData) -> bool:
        """
        Persist a receipt across all tables.

        Returns ``True`` if saved, ``False`` if a duplicate already exists
        (same content hash). Callers can distinguish via the return value
        rather than catching an exception.
        """
        ...

    def get(self, receipt_id: str) -> ReceiptData | None:
        """Fetch a receipt by content-hash ID."""
        ...

    def exists(self, receipt_id: str) -> bool:
        """Return True if a receipt with this ID is already stored."""
        ...

    def delete(self, receipt_id: str) -> bool:
        """Remove a receipt and all its child rows. Returns True if deleted."""
        ...

    def list_all(self) -> Iterable[ReceiptData]:
        """All receipts, most recently dated first."""
        ...

    def find_by_period(self, start: date, end: date) -> Iterable[ReceiptData]:
        """Receipts whose date falls within [start, end] inclusive."""
        ...

    def find_by_category(self, category: str) -> Iterable[ReceiptData]:
        """Receipts matching the given category."""
        ...

    def find_by_type(self, receipt_type: str) -> Iterable[ReceiptData]:
        """
        Receipts of a given type.

        Args:
            receipt_type: ``"purchase"`` or ``"sale"``.
        """
        ...

    def get_or_create_counterparty(self, counterparty: Counterparty) -> Counterparty:
        """
        Return the existing counterparty if one matches by VAT ID or name,
        otherwise insert and return a new one.
        """
        ...

    def close(self) -> None:
        """Release connections."""
        ...