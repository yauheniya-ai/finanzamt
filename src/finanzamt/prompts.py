"""
finanzamt.prompts
~~~~~~~~~~~~~~~~~
LLM prompt templates used during receipt extraction.

Kept separate from config so prompts can be versioned, tested, and iterated
independently from runtime configuration.
"""

from __future__ import annotations

from string import Template

# ---------------------------------------------------------------------------
# Supported receipt categories
# ---------------------------------------------------------------------------

RECEIPT_CATEGORIES = [
    "material",
    "equipment",
    "internet",
    "telecommunication",
    "software",
    "education",
    "travel",
    "utilities",
    "insurance",
    "taxes",
    "other",
]

_CATEGORY_LIST = ", ".join(RECEIPT_CATEGORIES)

# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT_TEMPLATE: str = f"""
You are a financial document processing agent specialising in German receipts and invoices.
Extract the following structured information from the receipt text provided below.

──────────────────────────────────────────────────────
RECEIPT HEADER
──────────────────────────────────────────────────────
1. vendor          — Business or store name
2. vendor_address  — Full address of the vendor (street, city, postal code)
3. receipt_number  — Invoice or receipt reference number
4. receipt_date    — Date in YYYY-MM-DD format
5. total_amount    — Grand total as a decimal number
6. vat_percentage  — VAT rate applied (e.g. 19.0 for 19 %)
7. vat_amount      — Absolute VAT amount as a decimal number
8. category        — One of: {_CATEGORY_LIST}

──────────────────────────────────────────────────────
LINE ITEMS (repeat for every purchased item)
──────────────────────────────────────────────────────
- description  — Item name or description
- quantity     — Numeric quantity (null if not stated)
- unit_price   — Price per unit as a decimal (null if not stated)
- total_price  — Line-item total as a decimal
- category     — One of: {_CATEGORY_LIST}
- vat_rate     — VAT rate for this item as a decimal (e.g. 19.0)

──────────────────────────────────────────────────────
RECEIPT TEXT
──────────────────────────────────────────────────────
{{text}}

──────────────────────────────────────────────────────
RESPONSE FORMAT
──────────────────────────────────────────────────────
Respond with ONLY a valid JSON object — no markdown fences, no explanation:

{{{{
  "vendor":          "string",
  "vendor_address":  "string or null",
  "receipt_number":  "string or null",
  "receipt_date":    "YYYY-MM-DD or null",
  "total_amount":    0.00,
  "vat_percentage":  0.00,
  "vat_amount":      0.00,
  "category":        "string",
  "items": [
    {{{{
      "description": "string",
      "quantity":    1,
      "unit_price":  0.00,
      "total_price": 0.00,
      "category":    "string",
      "vat_rate":    19.0
    }}}}
  ]
}}}}

Rules:
- Use null for any field that cannot be determined from the text.
- All monetary values must be decimal numbers (not strings).
- receipt_date must be in YYYY-MM-DD format or null.
- Output must be valid JSON parseable by Python's json.loads().
"""


def build_extraction_prompt(text: str) -> str:
    """
    Render the extraction prompt with the given receipt text.

    Args:
        text: Raw OCR text extracted from the receipt.

    Returns:
        Fully formatted prompt string ready to send to the LLM.
    """
    return EXTRACTION_PROMPT_TEMPLATE.format(text=text)


__all__ = [
    "RECEIPT_CATEGORIES",
    "EXTRACTION_PROMPT_TEMPLATE",
    "build_extraction_prompt",
]