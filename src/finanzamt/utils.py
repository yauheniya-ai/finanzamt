"""
finanzamt.utils
~~~~~~~~~~~~~~~
Heuristic rule-based extraction utilities used as a fallback when the LLM
is unavailable or returns incomplete data.

These functions are intentionally simple and conservative — they prefer
returning ``None`` over returning plausibly wrong values.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

# Category keywords aligned with RECEIPT_CATEGORIES in prompts.py.
# The LLM and the rule-based fallback must agree on category names.
from .agents.prompts import RECEIPT_CATEGORIES

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Keyword → receipt category mapping (German terms only — English handled by LLM)
_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "material":          ["papier", "rohstoff", "verbrauch", "büromaterial", "druckerpapier"],
    "equipment":         ["gerät", "drucker", "monitor", "tastatur", "maus", "server", "hardware", "maschine"],
    "software":          ["software", "lizenz", "abo", "subscription", "app", "cloud", "saas"],
    "internet":          ["internet", "dsl", "glasfaser", "breitband", "hosting", "domain"],
    "telecommunication": ["telefon", "handy", "mobilfunk", "sim", "telekom", "vodafone", "o2", "mobilität"],
    "travel":            ["hotel", "flug", "bahn", "taxi", "mietwagen", "reise", "übernachtung"],
    "education":         ["kurs", "seminar", "buch", "schulung", "weiterbildung", "studium", "zertifikat"],
    "utilities":         ["strom", "gas", "wasser", "heizung", "nebenkosten", "entsorgung"],
    "insurance":         ["versicherung", "haftpflicht", "police", "prämie"],
    "taxes":             ["steuer", "finanzamt", "steuerberater", "gebühr", "abgabe"],
}

# Keywords that anchor a line as the grand total (checked before max() fallback)
_TOTAL_KEYWORDS = ["gesamt", "gesamtbetrag", "total", "summe", "endbetrag", "brutto", "rechnungsbetrag"]

# German month names → month number
_MONTH_MAP: Dict[str, int] = {
    "januar": 1,   "january": 1,
    "februar": 2,  "february": 2,
    "märz": 3,     "marz": 3,     "march": 3,
    "april": 4,
    "mai": 5,      "may": 5,
    "juni": 6,     "june": 6,
    "juli": 7,     "july": 7,
    "august": 8,
    "september": 9,
    "oktober": 10, "october": 10,
    "november": 11,
    "dezember": 12, "december": 12,
}

# Date regexes in (pattern, order) pairs.
# order: "dmy" | "ymd" so the unpacking is unambiguous.
_DATE_PATTERNS: List[tuple[str, str]] = [
    (r'\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b',        "dmy"),  # DD.MM.YYYY
    (r'\b(\d{1,2})\.(\d{1,2})\.(\d{2})\b',         "dmy"),  # DD.MM.YY
    (r'\b(\d{4})-(\d{2})-(\d{2})\b',               "ymd"),  # YYYY-MM-DD  ← fixed order
    (r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b',           "dmy"),  # DD/MM/YYYY
    (r'\b(\d{1,2})\s+([A-Za-zÄÖÜäöü]+)\s+(\d{4})\b', "dmy"),  # 12 Januar 2023
]

# Amount regexes — German locale (period = thousands sep, comma = decimal)
_AMOUNT_PATTERNS = [
    r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*€',
    r'€\s*(\d{1,3}(?:\.\d{3})*,\d{2})',
    r'EUR\s*(\d{1,3}(?:\.\d{3})*,\d{2})',
    r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*EUR',
]

# VAT line regexes
_VAT_PATTERNS = [
    r'(\d{1,2}(?:,\d{1,2})?)\s*%.*?(\d{1,3}(?:\.\d{3})*,\d{2})\s*€',
    r'MwSt\.?\s*(\d{1,2}(?:,\d{1,2})?)\s*%.*?(\d{1,3}(?:\.\d{3})*,\d{2})',
    r'VAT\s*(\d{1,2}(?:,\d{1,2})?)\s*%.*?(\d{1,3}(?:\.\d{3})*,\d{2})',
]

# Item line regexes — ordered most-specific first so the quantity×price
# pattern is tried before the generic description+price fallback.
_ITEM_PATTERNS = [
    r'^(\d+(?:,\d+)?)\s*[xX]\s*(.+?)\s+(\d{1,3}(?:\.\d{3})*,\d{2})\s*€?\s*$',
    r'^(.+?)\s*@\s*(\d{1,3}(?:\.\d{3})*,\d{2})\s*=\s*(\d{1,3}(?:\.\d{3})*,\d{2})\s*€?\s*$',
    r'^(.+?)\s+(\d{1,3}(?:\.\d{3})*,\d{2})\s*€?\s*$',
]

# Lines that look like receipt boilerplate rather than company names
_SKIP_HEADER_WORDS = frozenset([
    "receipt", "rechnung", "kassenbon", "beleg", "quittung",
    "datum", "uhrzeit", "kasse", "bon",
])


# ---------------------------------------------------------------------------
# Helper: German amount string → Decimal
# ---------------------------------------------------------------------------

def _parse_german_amount(s: str) -> Optional[Decimal]:
    """Convert a German-format amount string (e.g. '1.234,56') to Decimal."""
    try:
        return Decimal(s.replace(".", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


# ---------------------------------------------------------------------------
# DataExtractor
# ---------------------------------------------------------------------------

class DataExtractor:
    """
    Heuristic text extraction for receipts.

    All methods are static — instantiate the class or call methods directly.
    """

    # ------------------------------------------------------------------
    # Company / vendor
    # ------------------------------------------------------------------

    @staticmethod
    def extract_company_name(text: str) -> Optional[str]:
        """
        Return the first non-trivial line from the top of the receipt.

        Skips blank lines, lines that start with a digit (dates, amounts),
        and lines containing common boilerplate words.
        """
        for line in text.splitlines()[:8]:
            line = line.strip()
            if not line:
                continue
            if re.match(r"^\d", line):
                continue
            if len(line) < 3:
                continue
            if any(w in line.lower() for w in _SKIP_HEADER_WORDS):
                continue
            return line
        return None

    # ------------------------------------------------------------------
    # Date
    # ------------------------------------------------------------------

    @staticmethod
    def extract_date(text: str) -> Optional[datetime]:
        """
        Return the first parseable date found in the text.

        Handles DD.MM.YYYY, YYYY-MM-DD, DD/MM/YYYY and German month names.
        Two-digit years are interpreted as 2000+ if < 50, else 1900+.
        """
        for pattern, order in _DATE_PATTERNS:
            for groups in re.findall(pattern, text):
                try:
                    a, b, c = groups
                    if order == "ymd":
                        year, month_raw, day = a, b, c
                    else:
                        day, month_raw, year = a, b, c

                    # Resolve year
                    year = int(year)
                    if year < 100:
                        year = 2000 + year if year < 50 else 1900 + year

                    # Resolve month (numeric or German/English name)
                    if month_raw.isdigit():
                        month = int(month_raw)
                    else:
                        month = _MONTH_MAP.get(month_raw.lower())
                        if month is None:
                            continue

                    return datetime(year, month, int(day))
                except (ValueError, TypeError):
                    continue
        return None

    # ------------------------------------------------------------------
    # Amounts
    # ------------------------------------------------------------------

    @staticmethod
    def extract_amounts(text: str) -> Dict[str, Any]:
        """
        Extract monetary amounts from text.

        Strategy:
        1. Scan lines that contain a total-indicating keyword; use the
           amount on that line as the grand total.
        2. Fall back to the largest amount found in the document.

        Returns ``{"total": Decimal | None, "all": [Decimal, ...]}``.
        """
        all_amounts: List[Decimal] = []
        total_amount: Optional[Decimal] = None

        for line in text.splitlines():
            line_lower = line.lower()
            is_total_line = any(kw in line_lower for kw in _TOTAL_KEYWORDS)

            for pattern in _AMOUNT_PATTERNS:
                for match in re.findall(pattern, line):
                    amount = _parse_german_amount(match)
                    if amount is None:
                        continue
                    all_amounts.append(amount)
                    # Prefer a total-keyword-anchored amount
                    if is_total_line and total_amount is None:
                        total_amount = amount

        if total_amount is None and all_amounts:
            total_amount = max(all_amounts)  # last-resort fallback

        return {"total": total_amount, "all": all_amounts}

    # ------------------------------------------------------------------
    # VAT
    # ------------------------------------------------------------------

    @staticmethod
    def extract_vat_info(text: str) -> Dict[str, Optional[Decimal]]:
        """Extract the first VAT percentage + absolute amount found."""
        for pattern in _VAT_PATTERNS:
            for match in re.findall(pattern, text, re.IGNORECASE):
                try:
                    vat_pct = Decimal(match[0].replace(",", "."))
                    vat_amt = _parse_german_amount(match[1])
                    if vat_pct and vat_amt:
                        return {"vat_percentage": vat_pct, "vat_amount": vat_amt}
                except (InvalidOperation, IndexError):
                    continue
        return {"vat_percentage": None, "vat_amount": None}

    # ------------------------------------------------------------------
    # Line items
    # ------------------------------------------------------------------

    @staticmethod
    def extract_items(text: str) -> List[Dict[str, Any]]:
        """
        Parse individual receipt line items.

        Returns a list of dicts with keys matching the LLM extraction
        schema so both paths feed ``_build_receipt_data`` identically.
        """
        items: List[Dict[str, Any]] = []

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            for pattern in _ITEM_PATTERNS:
                m = re.match(pattern, line)
                if not m:
                    continue
                groups = m.groups()

                if len(groups) == 2:                    # description + price
                    description = groups[0].strip()
                    total_price = _parse_german_amount(groups[1])
                    if total_price is None:
                        continue
                    items.append({
                        "description": description,
                        "quantity":    None,
                        "unit_price":  None,
                        "total_price": float(total_price),
                        "category":    DataExtractor._categorize_item(description),
                        "vat_rate":    None,
                    })

                elif len(groups) == 3:                  # qty × description = price
                    try:
                        qty = Decimal(groups[0].replace(",", "."))
                    except InvalidOperation:
                        continue
                    description = groups[1].strip()
                    total_price = _parse_german_amount(groups[2])
                    if total_price is None:
                        continue
                    unit_price = total_price / qty if qty > 0 else None
                    items.append({
                        "description": description,
                        "quantity":    float(qty),
                        "unit_price":  float(unit_price) if unit_price else None,
                        "total_price": float(total_price),
                        "category":    DataExtractor._categorize_item(description),
                        "vat_rate":    None,
                    })

                break  # matched a pattern — don't try the others

        return items

    @staticmethod
    def _categorize_item(description: str) -> str:
        """
        Map an item description to a receipt category.

        Returns a string that is always a valid ``ReceiptCategory`` value.
        """
        lower = description.lower()
        for category, keywords in _CATEGORY_KEYWORDS.items():
            if any(kw in lower for kw in keywords):
                return category
        return "other"


# ---------------------------------------------------------------------------
# JSON cleaning
# ---------------------------------------------------------------------------

def clean_json_response(response: str) -> str:
    """
    Extract and sanitise a JSON object from an LLM response string.

    Handles:
    - Markdown code fences (```json … ```)
    - Trailing commas in objects and arrays
    - Unquoted keys — only attempted when the extracted candidate is not
      already valid JSON, to avoid corrupting URLs or colons inside strings

    Returns an empty JSON object ``{}`` on total failure so callers can
    always call ``json.loads()`` on the result.
    """
    # Strip markdown fences
    response = re.sub(r"```(?:json)?\s*", "", response)
    response = re.sub(r"```\s*$", "", response, flags=re.MULTILINE)
    response = response.strip()

    # Remove trailing commas before } or ]
    response = re.sub(r",\s*([}\]])", r"\1", response)

    # Extract the outermost JSON object
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if not match:
        logger.warning("No JSON object found in LLM response.")
        return "{}"

    candidate = match.group(0)

    # Try to parse as-is first — if it's already valid JSON, return immediately.
    # This prevents any regex from corrupting URLs or colons inside string values.
    try:
        json.loads(candidate)
        return candidate
    except json.JSONDecodeError:
        pass

    # Only reach here when the JSON is actually malformed.
    # Attempt to quote unquoted object keys.
    # Pattern matches a word that is:
    #   - preceded by { or , (with optional whitespace) — i.e. in key position
    #   - not already quoted
    #   - followed by optional whitespace and a colon
    fixed = re.sub(
        r'([{,]\s*)([A-Za-z_]\w*)\s*:',
        lambda m: f'{m.group(1)}"{m.group(2)}":',
        candidate,
    )

    try:
        json.loads(fixed)
        return fixed
    except json.JSONDecodeError as exc:
        logger.warning("Could not produce valid JSON after cleaning: %s", exc)
        return "{}"


# ---------------------------------------------------------------------------
# Shared parse helpers (used by agent.py)
# ---------------------------------------------------------------------------

def parse_decimal(value: Any) -> Optional[Decimal]:
    """Safely coerce any value to ``Decimal``, returning ``None`` on failure."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def parse_date(date_str: str) -> Optional[datetime]:
    """
    Parse an ISO-format date string (``YYYY-MM-DD``) to ``datetime``.

    Also accepts common European formats as a fallback.  Uses explicit
    format strings rather than ``%B``/``%b`` to avoid locale dependency.
    """
    if not date_str:
        return None

    formats = [
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    # Last resort: delegate to DataExtractor which handles German month names
    return DataExtractor.extract_date(date_str)
