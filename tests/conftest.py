"""
tests/conftest.py
~~~~~~~~~~~~~~~~~
Shared pytest fixtures for the finanzamt test suite.
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from finanzamt.config import Config
from finanzamt.models import ExtractionResult, ReceiptCategory, ReceiptData, ReceiptItem


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@pytest.fixture
def default_config() -> Config:
    """A Config instance with all default values (no .env side-effects)."""
    return Config(
        _env_file=None,  # type: ignore[call-arg]
    )


# ---------------------------------------------------------------------------
# Model instances
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_item() -> ReceiptItem:
    return ReceiptItem(
        description="Druckerpapier A4",
        total_price=Decimal("12.99"),
        quantity=Decimal("2"),
        unit_price=Decimal("6.495"),
        category=ReceiptCategory("material"),
        vat_rate=Decimal("19.0"),
    )


@pytest.fixture
def sample_receipt(sample_item) -> ReceiptData:
    return ReceiptData(
        vendor="Bürobedarf GmbH",
        vendor_address="Musterstraße 1, 10115 Berlin",
        receipt_number="RE-2024-001",
        receipt_date=datetime(2024, 3, 15),
        total_amount=Decimal("25.90"),
        vat_percentage=Decimal("19.0"),
        vat_amount=Decimal("4.13"),
        category=ReceiptCategory("material"),
        raw_text="Bürobedarf GmbH\nDruckerpapier A4 2x 12,99 EUR\nGesamt 25,90 EUR",
        items=[sample_item],
    )


@pytest.fixture
def successful_result(sample_receipt) -> ExtractionResult:
    return ExtractionResult(
        success=True,
        data=sample_receipt,
        processing_time=1.234,
    )


@pytest.fixture
def failed_result() -> ExtractionResult:
    return ExtractionResult(
        success=False,
        error_message="No text could be extracted from the receipt.",
        processing_time=0.12,
    )


# ---------------------------------------------------------------------------
# Sample OCR texts
# ---------------------------------------------------------------------------

@pytest.fixture
def german_receipt_text() -> str:
    return """
Bürobedarf GmbH
Musterstraße 1
10115 Berlin

Datum: 15.03.2024
Rechnungsnummer: RE-2024-001

Druckerpapier A4   2x  6,50 €   13,00 €
Kugelschreiber     5x  0,99 €    4,95 €

Zwischensumme                   17,95 €
MwSt. 19%                        3,41 €
Gesamtbetrag                    21,36 €

Vielen Dank für Ihren Einkauf!
""".strip()


@pytest.fixture
def llm_json_response() -> dict:
    """A valid LLM extraction response dict."""
    return {
        "vendor": "Bürobedarf GmbH",
        "vendor_address": "Musterstraße 1, 10115 Berlin",
        "receipt_number": "RE-2024-001",
        "receipt_date": "2024-03-15",
        "total_amount": 21.36,
        "vat_percentage": 19.0,
        "vat_amount": 3.41,
        "category": "material",
        "items": [
            {
                "description": "Druckerpapier A4",
                "quantity": 2,
                "unit_price": 6.50,
                "total_price": 13.00,
                "category": "material",
                "vat_rate": 19.0,
            },
            {
                "description": "Kugelschreiber",
                "quantity": 5,
                "unit_price": 0.99,
                "total_price": 4.95,
                "category": "material",
                "vat_rate": 19.0,
            },
        ],
    }
