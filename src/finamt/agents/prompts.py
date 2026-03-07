"""
finamt.agents.prompts
~~~~~~~~~~~~~~~~~~~~~~~~
Short, focused prompts for the 4-agent sequential extraction pipeline.
Pattern: instruction → schema → text → output reminder (sandwich).
"""

from __future__ import annotations

RECEIPT_CATEGORIES = [
    "services", "consulting", "products", "licensing",
    "material", "equipment", "internet", "telecommunication",
    "software", "education", "travel", "utilities",
    "insurance", "taxes", "other",
]

_CATS = "|".join(RECEIPT_CATEGORIES)

# ---------------------------------------------------------------------------
# Agent 1 — Metadata: receipt number, date, category
# ---------------------------------------------------------------------------

AGENT1_TEMPLATE = """\
Extract receipt number, date, and category from the text below.
Return only this JSON, no other text:
{{"receipt_number": null, "receipt_date": "YYYY-MM-DD or null", "category": "{cats}"}}

TEXT:
{text}

Return only JSON:"""

# ---------------------------------------------------------------------------
# Agent 2 — Counterparty
# ---------------------------------------------------------------------------

AGENT2_TEMPLATE = """\
Extract the {party} from the receipt text below.
Return only this JSON, no other text:
{{"name": null, "vat_id": null, "tax_number": null, "street_and_number": null, \
"postcode": null, "city": null, "state": null, "country": null}}

Rules: name = actual business/person name, \
vat_id = USt-IdNr. e.g. DE123456789, \
tax_number = Steuernummer e.g. 123/456/78901. \


TEXT:
{text}

Return only JSON:"""

# ---------------------------------------------------------------------------
# Agent 3 — Amounts
# ---------------------------------------------------------------------------

AGENT3_TEMPLATE = """\
Extract the financial amounts from the receipt text below.
Return only this JSON, no other text:
{{"total_amount": null, "vat_percentage": null, "vat_amount": null}}

Rules: all values are numbers, not strings. \
German number format "1.234,56" means 1234.56. \
vat_percentage is the rate e.g. 19.0 for 19%%. \
vat_amount is the absolute tax amount in currency, not the rate.

TEXT:
{text}

Return only JSON:"""

# ---------------------------------------------------------------------------
# Agent 4 — Line items
# ---------------------------------------------------------------------------

AGENT4_TEMPLATE = """\
Extract all line items from the receipt text below.
Return only this JSON, no other text:
{{"items": [{{"description": null, "vat_rate": null, "vat_amount": null, "total_price": null}}]}}

Rules: all numeric values are numbers, not strings. \
German number format "1.234,56" means 1234.56. \
vat_rate is the percentage e.g. 19.0. \
If no line items exist return {{"items": []}}.

TEXT:
{text}

Return only JSON:"""


# ---------------------------------------------------------------------------
# Builder functions
# ---------------------------------------------------------------------------

def _truncate(text: str, max_chars: int = 3000) -> str:
    """Keep prompts short for local models."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[... truncated ...]"


def build_agent1_prompt(text: str) -> str:
    return AGENT1_TEMPLATE.format(cats=_CATS, text=_truncate(text))


def build_agent2_prompt(text: str, receipt_type: str) -> str:
    if receipt_type == "purchase":
        party = "vendor/supplier"
    else:
        party = "client/customer (look for 'An:', 'Bill to:', 'Kunde:', 'Rechnungsempfaenger:')"
    return AGENT2_TEMPLATE.format(party=party, text=_truncate(text))


def build_agent3_prompt(text: str) -> str:
    return AGENT3_TEMPLATE.format(text=_truncate(text))


def build_agent4_prompt(text: str) -> str:
    return AGENT4_TEMPLATE.format(text=_truncate(text))


__all__ = [
    "RECEIPT_CATEGORIES",
    "build_agent1_prompt",
    "build_agent2_prompt",
    "build_agent3_prompt",
    "build_agent4_prompt",
]