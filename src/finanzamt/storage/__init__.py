"""
finanzamt.storage
~~~~~~~~~~~~~~~~~
Pluggable persistence layer for receipts.

Default backend: SQLite at ``~/.finanzamt/receipts.db``.

Usage::

    from finanzamt.storage import get_repository

    repo = get_repository()                     # SQLite default
    repo.save(receipt)
    for r in repo.list_all():
        print(r.vendor, r.total_amount)
"""

from .base import ReceiptRepository
from .sqlite import SQLiteRepository


def get_repository(db_path=None) -> SQLiteRepository:
    """Return the default SQLite repository, optionally at a custom path."""
    return SQLiteRepository(db_path=db_path)


__all__ = ["ReceiptRepository", "SQLiteRepository", "get_repository"]
