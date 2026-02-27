"""
finanzamt.agents.prompts
~~~~~~~~~~~~~~~~~~~~~~~~
Prompt templates for each agent in the extraction pipeline.

Agent 1 (text):   OCR text + rule-based hints → json1
Agent 2 (vision): PNG image → json2
Agent 3 (validator): json1 + json2 → json3 (unified, validated)
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

_CATS = ", ".join(RECEIPT_CATEGORIES)

_JSON_SCHEMA = """\
{
  "receipt_type": "purchase",
  "counterparty_name": null,
  "counterparty_tax_number": null,
  "counterparty_vat_id": null,
  "counterparty_address": {"street": null, "street_number": null, "postcode": null, "city": null, "country": null},
  "receipt_number": null,
  "receipt_date": null,
  "total_amount": null,
  "vat_percentage": null,
  "vat_amount": null,
  "category": "other",
  "items": [
    {"description": null, "quantity": null, "unit_price": null, "total_price": null, "category": "other", "vat_rate": null}
  ]
}"""

# ---------------------------------------------------------------------------
# Agent 1 — Text extraction
# ---------------------------------------------------------------------------

AGENT1_PROMPT_TEMPLATE = """\
You are a financial document data extraction agent for German receipts and invoices.
You will receive:
1. The OCR text content of the document
2. A partial extraction from a rule-based system (may have nulls — verify and complete it)

Your task: return a single valid JSON object with all fields extracted from the document.

DOCUMENT TYPE
receipt_type: "purchase" (you paid this — vendor issued it) or "sale" (you issued this to a client).

COUNTERPARTY
For purchases: the vendor/supplier name and address.
For sales: the client/customer — look for sections labelled "An:", "Rechnungsempfänger:", "Kunde:", "Bill to:".
counterparty_name: the actual business or person name.
  DO NOT use field labels as the name. Labels end with ":" and include:
  Kundennr., Rechnungsnr., Datum, Betrag, Steuernummer, IBAN, BIC, E-Mail, Telefon, Web, www.
counterparty_tax_number: German Steuernummer (format 123/456/78901), or null.
counterparty_vat_id: EU VAT ID (format DE123456789), or null.
counterparty_address: street (name only), street_number (building number), postcode, city, country.

DOCUMENT FIELDS
receipt_number: invoice/receipt reference number, or null.
receipt_date: date in YYYY-MM-DD format, or null. German format: DD.MM.YYYY → YYYY-MM-DD.
total_amount: grand total as a decimal number. German format: "1.234,56 €" → 1234.56. Never a string.
vat_percentage: VAT rate as a number e.g. 19.0 for 19%% MwSt, or null.
vat_amount: absolute VAT amount as a decimal number, or null.

CATEGORY — choose exactly one from: {cats}
Mapping:
- internet: ISP, broadband, hosting, domain, webhosting
- telecommunication: phone bills, mobile, SIM, Vodafone, Telekom, O2, 1&1
- software: app subscriptions, SaaS, software licenses bought
- education: courses, books, training, conferences, workshops, Udemy, Coursera
- travel: flights, hotels, trains, taxis, rental car, fuel, parking
- equipment: hardware, computers, monitors, office furniture, tools
- material: raw materials, office supplies, packaging, printing
- utilities: electricity, gas, water, heating, waste disposal
- insurance: any Versicherung, policy, premium
- taxes: tax payments, Steuerberater, notary, legal fees, Finanzamt
- services: freelance/consulting work YOU billed to a client (sale invoice)
- consulting: advisory/consulting project YOU billed to a client (sale invoice)
- products: physical goods YOU sold to a client (sale invoice)
- licensing: software/IP rights YOU licensed to a client (sale invoice)
- other: only if truly none of the above apply

LINE ITEMS: extract all individual positions. For each: description, quantity, unit_price, total_price, category (from list above), vat_rate.

RULE-BASED HINTS (verify these, correct if wrong, fill in what is null):
{hints}

DOCUMENT TEXT:
{text}

OUTPUT: valid JSON only, no markdown, no explanation, no trailing text after the closing brace.
{schema}
"""

# ---------------------------------------------------------------------------
# Agent 2 — Vision extraction
# ---------------------------------------------------------------------------

AGENT2_PROMPT_TEMPLATE = """\
You are a financial document data extraction agent. You will receive an image of a German receipt or invoice.

Extract all visible information and return a single valid JSON object.

DOCUMENT TYPE
receipt_type: "purchase" (document was issued TO you) or "sale" (you issued this document).

COUNTERPARTY
For purchases: the issuing company name, address, VAT ID.
For sales: the recipient/client name and address — look for "An:", "Rechnungsempfänger:", "Kunde:".
counterparty_name: actual business name only. NOT field labels ending with ":".
counterparty_tax_number: Steuernummer if visible, or null.
counterparty_vat_id: USt-IdNr. or VAT ID if visible (format DE123456789), or null.
counterparty_address: street, street_number, postcode, city, country.

DOCUMENT FIELDS
receipt_number: invoice or receipt number, or null.
receipt_date: YYYY-MM-DD, or null.
total_amount: total amount as decimal. German "1.234,56 €" → 1234.56.
vat_percentage: VAT rate as number e.g. 19.0, or null.
vat_amount: absolute VAT as decimal, or null.

CATEGORY — choose exactly one from: {cats}
{cat_mapping}

LINE ITEMS: all line positions visible in the document.

OUTPUT: valid JSON only, no markdown, no explanation.
{schema}
"""

_CAT_MAPPING = """\
- internet: ISP, broadband, hosting, domain
- telecommunication: phone, mobile, SIM, Vodafone, Telekom, O2, 1&1
- software: software, SaaS, app subscriptions, licenses
- education: courses, training, books, workshops
- travel: flights, hotels, trains, taxis, fuel
- equipment: hardware, computers, office furniture
- material: supplies, packaging, raw materials
- utilities: electricity, gas, water
- insurance: Versicherung, policy
- taxes: Steuer, Finanzamt, legal, notary
- services/consulting/products/licensing: only for sale invoices (you billed a client)
- other: only if truly none of the above"""

# ---------------------------------------------------------------------------
# Agent 3 — Validator
# ---------------------------------------------------------------------------

AGENT3_PROMPT_TEMPLATE = """\
You are a data validation agent. You receive two JSON extractions of the same financial document
produced by two independent extraction agents. Your task is to produce one unified, correct JSON.

MERGE RULES — apply in order:
1. Prefer a non-null value over null. If one agent has a value and the other has null, use the non-null value.
2. For numeric fields (total_amount, vat_amount, vat_percentage): apply these sanity checks:
   - total_amount must be > 0
   - vat_amount must be < total_amount
   - vat_percentage must be between 0 and 100
   - If vat_percentage and vat_amount are both present, check: vat_amount ≈ total_amount * vat_percentage / (100 + vat_percentage)
     Tolerance: 5%%. If one value fails the check, prefer the other agent's value.
3. For receipt_date: prefer the value in YYYY-MM-DD format. If both are present and differ, prefer the one that looks like a plausible invoice date (not a future date beyond one year from now).
4. For counterparty_name: prefer longer, more complete names. Reject values that end with ":" or are obvious field labels.
5. For category: if both agents agree, use that value. If they disagree, use the value that is NOT "other" — unless both say "other".
6. For items: merge lists. Remove exact duplicates. Keep all unique items.
7. receipt_type: if either agent produced a non-default value (i.e. "sale"), prefer that.

EXTRACTION 1 (text agent):
{json1}

EXTRACTION 2 (vision agent):
{json2}

OUTPUT: a single valid JSON object with the merged result. No markdown, no explanation, no text before or after the JSON.
{schema}
"""


def build_agent1_prompt(text: str, hints: dict) -> str:
    """Build Agent 1 prompt with OCR text and rule-based hints."""
    import json
    hints_str = json.dumps(hints, indent=2, ensure_ascii=False)
    # Truncate OCR text to avoid context overflow
    truncated = text[:5000] + ("\n[... truncated ...]" if len(text) > 5000 else "")
    return AGENT1_PROMPT_TEMPLATE.format(
        cats=_CATS,
        hints=hints_str,
        text=truncated,
        schema=_JSON_SCHEMA,
    )


def build_agent2_prompt() -> str:
    """Build Agent 2 prompt (image is passed separately via multimodal API)."""
    return AGENT2_PROMPT_TEMPLATE.format(
        cats=_CATS,
        cat_mapping=_CAT_MAPPING,
        schema=_JSON_SCHEMA,
    )


def build_agent3_prompt(json1: dict | None, json2: dict | None) -> str:
    """Build Agent 3 validator prompt from two extraction results."""
    import json
    j1 = json.dumps(json1, indent=2, ensure_ascii=False) if json1 else "null (agent failed)"
    j2 = json.dumps(json2, indent=2, ensure_ascii=False) if json2 else "null (agent failed)"
    return AGENT3_PROMPT_TEMPLATE.format(
        json1=j1,
        json2=j2,
        schema=_JSON_SCHEMA,
    )


__all__ = [
    "RECEIPT_CATEGORIES",
    "build_agent1_prompt",
    "build_agent2_prompt",
    "build_agent3_prompt",
]