"""
tests/test_storage.py
~~~~~~~~~~~~~~~~~~~~~
Tests for finanzamt.storage.sqlite — SQLiteRepository.

All tests use tmp_path so they never touch ~/.finanzamt/receipts.db.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest

from finanzamt.models import ReceiptCategory, ReceiptData, ReceiptItem
from finanzamt.storage.base import ReceiptRepository
from finanzamt.storage.sqlite import SQLiteRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path) -> SQLiteRepository:
    db = SQLiteRepository(db_path=tmp_path / "test.db")
    yield db
    db.close()


def _make_receipt(
    *,
    vendor: str = "Test GmbH",
    receipt_date: datetime | None = datetime(2024, 3, 15),
    total_amount: str | None = "119.00",
    vat_percentage: str | None = "19",
    vat_amount: str | None = "19.00",
    category: str = "software",
    items: list | None = None,
) -> ReceiptData:
    return ReceiptData(
        vendor=vendor,
        vendor_address="Musterstraße 1, 10115 Berlin",
        receipt_number="RE-2024-001",
        receipt_date=receipt_date,
        total_amount=Decimal(total_amount) if total_amount else None,
        vat_percentage=Decimal(vat_percentage) if vat_percentage else None,
        vat_amount=Decimal(vat_amount) if vat_amount else None,
        category=ReceiptCategory(category),
        raw_text="Test receipt text",
        items=items or [],
    )


def _make_item(
    description: str = "Python-Lizenz",
    total_price: str = "119.00",
    vat_rate: str = "19.0",
) -> ReceiptItem:
    return ReceiptItem(
        description=description,
        total_price=Decimal(total_price),
        quantity=Decimal("1"),
        unit_price=Decimal(total_price),
        category=ReceiptCategory("software"),
        vat_rate=Decimal(vat_rate),
    )


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

class TestProtocolConformance:
    def test_is_receipt_repository(self, repo):
        assert isinstance(repo, ReceiptRepository)


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class TestContextManager:
    def test_context_manager_closes_connection(self, tmp_path):
        with SQLiteRepository(db_path=tmp_path / "ctx.db") as repo:
            r = _make_receipt()
            repo.save(r)
        with pytest.raises(Exception):
            repo.get(r.id)   # connection closed — must raise


# ---------------------------------------------------------------------------
# save / get
# ---------------------------------------------------------------------------

class TestSaveGet:
    def test_save_and_retrieve(self, repo):
        r = _make_receipt()
        repo.save(r)
        found = repo.get(r.id)
        assert found is not None
        assert found.id == r.id
        assert found.vendor == "Test GmbH"

    def test_get_returns_none_for_unknown_id(self, repo):
        assert repo.get(str(uuid.uuid4())) is None

    def test_decimal_precision_preserved(self, repo):
        r = _make_receipt(total_amount="1234.56", vat_amount="197.32")
        repo.save(r)
        found = repo.get(r.id)
        assert found.total_amount == Decimal("1234.56")
        assert found.vat_amount == Decimal("197.32")

    def test_none_fields_round_trip(self, repo):
        r = _make_receipt(
            total_amount=None,
            vat_percentage=None,
            vat_amount=None,
            receipt_date=None,
        )
        repo.save(r)
        found = repo.get(r.id)
        assert found.total_amount is None
        assert found.vat_percentage is None
        assert found.vat_amount is None
        assert found.receipt_date is None

    def test_category_restored_as_receipt_category(self, repo):
        r = _make_receipt(category="travel")
        repo.save(r)
        found = repo.get(r.id)
        assert isinstance(found.category, ReceiptCategory)
        assert str(found.category) == "travel"

    def test_invalid_category_normalised_to_other(self, repo):
        r = _make_receipt(category="flying_cars")
        assert str(r.category) == "other"
        repo.save(r)
        assert str(repo.get(r.id).category) == "other"

    def test_upsert_replaces_existing(self, repo):
        r = _make_receipt(vendor="Original GmbH")
        repo.save(r)
        r.vendor = "Updated GmbH"
        repo.save(r)
        assert repo.get(r.id).vendor == "Updated GmbH"
        assert len(list(repo.list_all())) == 1

    def test_receipt_date_round_trips_as_datetime(self, repo):
        r = _make_receipt(receipt_date=datetime(2024, 6, 30))
        repo.save(r)
        found = repo.get(r.id)
        assert isinstance(found.receipt_date, datetime)
        assert found.receipt_date == datetime(2024, 6, 30)

    def test_vendor_address_and_receipt_number_preserved(self, repo):
        r = _make_receipt()
        repo.save(r)
        found = repo.get(r.id)
        assert found.vendor_address == "Musterstraße 1, 10115 Berlin"
        assert found.receipt_number == "RE-2024-001"


# ---------------------------------------------------------------------------
# Line items
# ---------------------------------------------------------------------------

class TestLineItems:
    def test_items_persisted_and_restored(self, repo):
        r = _make_receipt(items=[_make_item()])
        repo.save(r)
        found = repo.get(r.id)
        assert len(found.items) == 1
        assert found.items[0].description == "Python-Lizenz"

    def test_item_decimals_preserved(self, repo):
        r = _make_receipt(items=[_make_item(total_price="119.00", vat_rate="19.0")])
        repo.save(r)
        item = repo.get(r.id).items[0]
        assert item.total_price == Decimal("119.00")
        assert item.vat_rate == Decimal("19.0")

    def test_item_category_restored_as_receipt_category(self, repo):
        r = _make_receipt(items=[_make_item()])
        repo.save(r)
        assert isinstance(repo.get(r.id).items[0].category, ReceiptCategory)

    def test_empty_items_round_trip(self, repo):
        r = _make_receipt(items=[])
        repo.save(r)
        assert repo.get(r.id).items == []

    def test_multiple_items(self, repo):
        items = [_make_item(description=f"Item {i}") for i in range(1, 4)]
        r = _make_receipt(items=items)
        repo.save(r)
        found = repo.get(r.id)
        assert len(found.items) == 3
        assert {i.description for i in found.items} == {"Item 1", "Item 2", "Item 3"}

    def test_item_none_fields_survive_round_trip(self, repo):
        item = ReceiptItem(description="Bare item")   # all optional fields None
        r = _make_receipt(items=[item])
        repo.save(r)
        restored = repo.get(r.id).items[0]
        assert restored.quantity is None
        assert restored.unit_price is None
        assert restored.vat_rate is None


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

class TestDelete:
    def test_delete_existing_returns_true(self, repo):
        r = _make_receipt()
        repo.save(r)
        assert repo.delete(r.id) is True
        assert repo.get(r.id) is None

    def test_delete_nonexistent_returns_false(self, repo):
        assert repo.delete(str(uuid.uuid4())) is False

    def test_delete_only_removes_target(self, repo):
        r1 = _make_receipt(vendor="A")
        r2 = _make_receipt(vendor="B")
        repo.save(r1)
        repo.save(r2)
        repo.delete(r1.id)
        assert repo.get(r1.id) is None
        assert repo.get(r2.id) is not None


# ---------------------------------------------------------------------------
# list_all
# ---------------------------------------------------------------------------

class TestListAll:
    def test_empty_repo_returns_empty(self, repo):
        assert list(repo.list_all()) == []

    def test_returns_all_receipts(self, repo):
        for v in ("A GmbH", "B GmbH", "C GmbH"):
            repo.save(_make_receipt(vendor=v))
        assert len(list(repo.list_all())) == 3

    def test_ordered_by_date_descending(self, repo):
        repo.save(_make_receipt(vendor="Jan", receipt_date=datetime(2024, 1, 1)))
        repo.save(_make_receipt(vendor="Mar", receipt_date=datetime(2024, 3, 1)))
        repo.save(_make_receipt(vendor="Feb", receipt_date=datetime(2024, 2, 1)))
        dates = [r.receipt_date for r in repo.list_all()]
        assert dates == sorted(dates, reverse=True)


# ---------------------------------------------------------------------------
# find_by_period
# ---------------------------------------------------------------------------

class TestFindByPeriod:
    def test_returns_receipts_in_range(self, repo):
        repo.save(_make_receipt(vendor="Jan", receipt_date=datetime(2024, 1, 15)))
        repo.save(_make_receipt(vendor="Mar", receipt_date=datetime(2024, 3, 10)))
        repo.save(_make_receipt(vendor="Dec", receipt_date=datetime(2024, 12, 1)))
        result = list(repo.find_by_period(date(2024, 1, 1), date(2024, 3, 31)))
        assert {r.vendor for r in result} == {"Jan", "Mar"}

    def test_inclusive_start_and_end(self, repo):
        repo.save(_make_receipt(vendor="Start", receipt_date=datetime(2024, 1, 1)))
        repo.save(_make_receipt(vendor="End",   receipt_date=datetime(2024, 3, 31)))
        result = list(repo.find_by_period(date(2024, 1, 1), date(2024, 3, 31)))
        assert len(result) == 2

    def test_excludes_receipts_without_date(self, repo):
        repo.save(_make_receipt(vendor="NoDate", receipt_date=None))
        result = list(repo.find_by_period(date(2024, 1, 1), date(2024, 12, 31)))
        assert all(r.vendor != "NoDate" for r in result)

    def test_empty_range(self, repo):
        repo.save(_make_receipt(receipt_date=datetime(2024, 6, 1)))
        assert list(repo.find_by_period(date(2025, 1, 1), date(2025, 12, 31))) == []

    def test_accepts_datetime_bounds_without_type_error(self, repo):
        """Regression: passing datetime instead of date must not raise TypeError."""
        repo.save(_make_receipt(receipt_date=datetime(2024, 3, 15)))
        result = list(repo.find_by_period(datetime(2024, 1, 1), datetime(2024, 12, 31)))
        assert len(result) == 1


# ---------------------------------------------------------------------------
# find_by_category
# ---------------------------------------------------------------------------

class TestFindByCategory:
    def test_returns_matching_receipts(self, repo):
        repo.save(_make_receipt(vendor="Soft 1", category="software"))
        repo.save(_make_receipt(vendor="Travel", category="travel"))
        repo.save(_make_receipt(vendor="Soft 2", category="software"))
        result = list(repo.find_by_category("software"))
        assert len(result) == 2
        assert all(str(r.category) == "software" for r in result)

    def test_returns_empty_for_absent_category(self, repo):
        repo.save(_make_receipt(category="software"))
        assert list(repo.find_by_category("travel")) == []


# ---------------------------------------------------------------------------
# Persistence across re-opens
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_data_survives_close_and_reopen(self, tmp_path):
        db_path = tmp_path / "persist.db"
        r = _make_receipt(vendor="Persistent GmbH")
        with SQLiteRepository(db_path=db_path) as repo:
            repo.save(r)
        with SQLiteRepository(db_path=db_path) as repo2:
            found = repo2.get(r.id)
        assert found is not None
        assert found.vendor == "Persistent GmbH"

    def test_schema_migration_preserves_data(self, tmp_path):
        """Opening the same db twice must not wipe or duplicate rows."""
        db_path = tmp_path / "migrate.db"
        r = _make_receipt()
        with SQLiteRepository(db_path=db_path) as repo:
            repo.save(r)
        with SQLiteRepository(db_path=db_path) as repo2:
            all_receipts = list(repo2.list_all())
        assert len(all_receipts) == 1
