"""
tests/test_prompts.py
~~~~~~~~~~~~~~~~~~~~~
Tests for finanzamt.prompts — category list and prompt rendering.
"""

from __future__ import annotations

import pytest

from finanzamt.prompts import RECEIPT_CATEGORIES, build_extraction_prompt


class TestReceiptCategories:
    def test_is_list_of_strings(self):
        assert isinstance(RECEIPT_CATEGORIES, list)
        assert all(isinstance(c, str) for c in RECEIPT_CATEGORIES)

    def test_contains_expected_categories(self):
        expected = {
            "material", "equipment", "internet", "telecommunication",
            "software", "education", "travel", "utilities",
            "insurance", "taxes", "other",
        }
        assert expected == set(RECEIPT_CATEGORIES)

    def test_no_duplicates(self):
        assert len(RECEIPT_CATEGORIES) == len(set(RECEIPT_CATEGORIES))

    def test_other_is_present(self):
        assert "other" in RECEIPT_CATEGORIES


class TestBuildExtractionPrompt:
    def test_returns_string(self):
        result = build_extraction_prompt("some receipt text")
        assert isinstance(result, str)

    def test_receipt_text_injected(self):
        text = "UNIQUE_RECEIPT_CONTENT_XYZ"
        result = build_extraction_prompt(text)
        assert text in result

    def test_all_categories_mentioned(self):
        result = build_extraction_prompt("text")
        for cat in RECEIPT_CATEGORIES:
            assert cat in result

    def test_json_schema_in_prompt(self):
        result = build_extraction_prompt("text")
        # Key JSON fields must appear in the prompt schema
        for field in ("vendor", "total_amount", "vat_percentage", "vat_amount", "items"):
            assert field in result

    def test_vat_rate_field_complete(self):
        """Regression: old prompt had truncated 'vat_rate': decimal_number_or"""
        result = build_extraction_prompt("text")
        assert "decimal_number_or" not in result

    def test_empty_text_does_not_raise(self):
        result = build_extraction_prompt("")
        assert isinstance(result, str)

    def test_special_characters_in_text(self):
        text = 'Müller GmbH – "Bürobedarf" & Co. KG'
        result = build_extraction_prompt(text)
        assert text in result
