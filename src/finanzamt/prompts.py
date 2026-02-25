"""
finanzamt.prompts
~~~~~~~~~~~~~~~~~
LLM prompt templates for receipt extraction.
"""

from __future__ import annotations

RECEIPT_CATEGORIES = [
    # Revenue categories (sales)
    "services", "consulting", "products", "licensing",
    # Expense categories (purchases)
    "material", "equipment", "internet", "telecommunication",
    "software", "education", "travel", "utilities",
    "insurance", "taxes",
    # Fallback
    "other",
]

_CATEGORY_LIST = ", ".join(RECEIPT_CATEGORIES)

EXTRACTION_PROMPT_TEMPLATE: str = f"""You are a financial document processing agent for German receipts and invoices.
Extract structured data from the document text and return valid JSON only.

DOCUMENT TYPE
receipt_type: "purchase" (you paid this) or "sale" (you invoiced a client). Default: "purchase".

COUNTERPARTY
For purchases: the vendor/supplier who issued the document.
For sales: the client/customer you are billing — look for "An:", "Rechnungsempfänger:", "Kunde:" sections.
counterparty_name — the actual business or person name. 
counterparty_tax_number (Steuernummer, or null), counterparty_vat_id (EU VAT ID e.g. DE123456789, or null)
counterparty_address: street, street_number, postcode, city, country (default "Germany")

DOCUMENT FIELDS
receipt_number, receipt_date (YYYY-MM-DD)
total_amount — grand total as a decimal number (e.g. 119.00). German format "1.234,56 €" → 1234.56
vat_percentage — e.g. 19.0 for 19% MwSt
vat_amount — absolute VAT in decimal (e.g. 21.35)

CATEGORY — choose the single best match from this list: {_CATEGORY_LIST}
Assign the most specific match based on the document content:
- internet: ISP bills, broadband, hosting, domain registrations
- telecommunication: phone bills, mobile plans, SIM cards
- software: app subscriptions, SaaS tools, licenses purchased
- education: courses, books, training, conferences, workshops
- travel: flights, hotels, trains, taxis, fuel, parking
- equipment: hardware, computers, office furniture, tools
- material: raw materials, office supplies, packaging
- utilities: electricity, gas, water, waste
- insurance: any insurance policy
- taxes: tax payments, notary, legal fees
- services: freelance work billed TO a client (sale invoices)
- consulting: advisory or consulting billed TO a client (sale invoices)
- products: physical goods sold TO a client (sale invoices)
- licensing: software or IP rights sold TO a client (sale invoices)
Never default to "other" unless the document genuinely matches none of the above.

LINE ITEMS: description, quantity, unit_price, total_price, category (from same list), vat_rate

DOCUMENT TEXT
{{text}}

OUTPUT — valid JSON, no markdown:
{{{{
  "receipt_type": null,
  "counterparty_name": null,
  "counterparty_tax_number": null,
  "counterparty_vat_id": null,
  "counterparty_address": {{{{"street": null, "street_number": null, "postcode": null, "city": null, "country": null}}}},
  "receipt_number": null,
  "receipt_date": null,
  "total_amount": null,
  "vat_percentage": null,
  "vat_amount": null,
  "category": null,
  "items": []
}}}}
Rules: null for unknown fields. Monetary values are numbers not strings. Output must parse with json.loads().
"""


def build_extraction_prompt(text: str) -> str:
    """Render the extraction prompt with the given receipt text."""
    # Hard-truncate OCR text to ~6000 chars (~1500 tokens) to stay within
    # context window even on small models (4096 ctx). First 6000 chars of an
    # invoice always contain all header fields; line items near the end are
    # less critical than totals and counterparty data.
    truncated = text[:6000] + ("\n[... truncated ...]" if len(text) > 6000 else "")
    return EXTRACTION_PROMPT_TEMPLATE.format(text=truncated)


__all__ = ["RECEIPT_CATEGORIES", "EXTRACTION_PROMPT_TEMPLATE", "build_extraction_prompt"]