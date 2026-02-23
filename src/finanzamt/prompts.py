"""
finanzamt.prompts
~~~~~~~~~~~~~~~~~
LLM prompt templates for receipt extraction.
"""

from __future__ import annotations

RECEIPT_CATEGORIES = [
    "material", "equipment", "internet", "telecommunication",
    "software", "education", "travel", "utilities",
    "insurance", "taxes", "other",
]

_CATEGORY_LIST = ", ".join(RECEIPT_CATEGORIES)

EXTRACTION_PROMPT_TEMPLATE: str = f"""
You are a financial document processing agent specialising in German receipts and invoices.
Extract the following structured information from the receipt text below.

──────────────────────────────────────────────────────
DOCUMENT TYPE
──────────────────────────────────────────────────────
receipt_type:
  "purchase"  — YOU paid this (vendor sold to you, VAT = Vorsteuer you reclaim)
  "sale"      — YOU issued this to a client (VAT = Umsatzsteuer you remit)
  Default to "purchase" when unclear.

──────────────────────────────────────────────────────
COUNTERPARTY (vendor if purchase, client if sale)
──────────────────────────────────────────────────────
counterparty_name        — Business or person name
counterparty_tax_number  — German Steuernummer e.g. "123/456/78901", or null
counterparty_vat_id      — EU VAT ID e.g. "DE123456789", or null
counterparty_address     — structured:
  street         — street name only (no number)
  street_number  — building number
  postcode       — postal code
  city           — city name
  country        — country name

──────────────────────────────────────────────────────
RECEIPT FIELDS
──────────────────────────────────────────────────────
receipt_number  — invoice/receipt reference, or null
receipt_date    — YYYY-MM-DD, or null
total_amount    — grand total as decimal
vat_percentage  — VAT rate e.g. 19.0, or null
vat_amount      — absolute VAT as decimal, or null
category        — one of: {_CATEGORY_LIST}

──────────────────────────────────────────────────────
LINE ITEMS
──────────────────────────────────────────────────────
description, quantity, unit_price, total_price, category, vat_rate

──────────────────────────────────────────────────────
RECEIPT TEXT
──────────────────────────────────────────────────────
{{text}}

──────────────────────────────────────────────────────
OUTPUT — valid JSON only, no markdown, no explanation:
──────────────────────────────────────────────────────
{{{{
  "receipt_type": "purchase",
  "counterparty_name": "string",
  "counterparty_tax_number": null,
  "counterparty_vat_id": null,
  "counterparty_address": {{{{
    "street": null, "street_number": null,
    "postcode": null, "city": null, "country": null
  }}}},
  "receipt_number": null,
  "receipt_date": null,
  "total_amount": 0.00,
  "vat_percentage": null,
  "vat_amount": null,
  "category": "other",
  "items": [
    {{{{"description": "string", "quantity": 1, "unit_price": 0.00,
        "total_price": 0.00, "category": "other", "vat_rate": null}}}}
  ]
}}}}

Rules:
- null for any field that cannot be determined.
- Monetary values are decimal numbers, never strings.
- Output must parse with Python json.loads().
"""


def build_extraction_prompt(text: str) -> str:
    """Render the extraction prompt with the given receipt text."""
    return EXTRACTION_PROMPT_TEMPLATE.format(text=text)


__all__ = ["RECEIPT_CATEGORIES", "EXTRACTION_PROMPT_TEMPLATE", "build_extraction_prompt"]