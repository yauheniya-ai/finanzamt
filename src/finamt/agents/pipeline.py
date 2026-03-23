"""
finamt.agents.pipeline
~~~~~~~~~~~~~~~~~~~~~~~~~~
4-agent sequential extraction pipeline.

  Agent 1  →  receipt number, date, category
  Agent 2  →  counterparty (vendor or client depending on receipt_type)
  Agent 3  →  amounts (total, vat_percentage, vat_amount)
  Agent 4  →  line items

Each agent runs sequentially (not parallel) for compatibility with local models.
After all 4 finish, results are merged in Python (no LLM validator step).

Debug output saved to ~/.finamt/debug/<receipt_id>/:
  agent1_prompt.txt / agent1_raw.txt / agent1_parsed.json
  agent2_prompt.txt / agent2_raw.txt / agent2_parsed.json
  agent3_prompt.txt / agent3_raw.txt / agent3_parsed.json
  agent4_prompt.txt / agent4_raw.txt / agent4_parsed.json
  final.json
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from finamt import progress as _progress
from typing import Optional, Union

from ..models import (
    Address, Counterparty,
    ReceiptCategory, ReceiptData, ReceiptItem, ReceiptType,
)
from ..utils import parse_date, parse_decimal
from .config import AgentsConfig
from .llm_caller import call_llm
from .prompts import (
    build_agent1_prompt,
    build_agent2_prompt,
    build_agent3_prompt,
    build_agent4_prompt,
)

_DEFAULT_DEBUG_ROOT = Path.home() / ".finamt" / "debug"


def _ts() -> str:
    return time.strftime("[%H:%M:%S]")


# ---------------------------------------------------------------------------
# Field validators — null-safe type coercions
# ---------------------------------------------------------------------------

def _str_or_none(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    # Reject obvious field labels (end with ":" or are pure numbers/short garbage)
    if s.endswith(":") or len(s) < 2:
        return None
    return s or None


def _float_or_none(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return None


def _validate_agent1(raw: Optional[dict]) -> dict:
    if not raw:
        return {}
    result: dict = {}
    if rn := _str_or_none(raw.get("receipt_number")):
        result["receipt_number"] = rn
    if rd := raw.get("receipt_date"):
        parsed = parse_date(str(rd))
        if parsed:
            result["receipt_date"] = parsed
    cat = raw.get("category", "other")
    try:
        result["category"] = ReceiptCategory(cat)
    except ValueError:
        result["category"] = ReceiptCategory("other")
    return result


def _validate_agent2(raw: Optional[dict]) -> dict:
    if not raw:
        return {}
    result: dict = {}
    for key in ("name", "vat_id", "tax_number", "street_and_number",
                "address_supplement", "postcode", "city", "state", "country"):
        if v := _str_or_none(raw.get(key)):
            result[key] = v
    return result


def _validate_agent3(raw: Optional[dict]) -> dict:
    if not raw:
        return {}
    result: dict = {}
    total = _float_or_none(raw.get("total_amount"))
    vat_pct = _float_or_none(raw.get("vat_percentage"))
    vat_amt = _float_or_none(raw.get("vat_amount"))

    if total is not None and total > 0:
        result["total_amount"] = total
    if vat_pct is not None and 0 <= vat_pct <= 100:
        result["vat_percentage"] = vat_pct
    if vat_amt is not None and vat_amt >= 0:
        # Sanity: vat_amount must be less than total if total known
        if total is None or vat_amt < total:
            result["vat_amount"] = vat_amt

    # Currency — accept only plausible ISO 4217 codes (2–4 uppercase letters)
    raw_cur = str(raw.get("currency") or "").strip().upper()
    result["currency"] = raw_cur if (2 <= len(raw_cur) <= 4 and raw_cur.isalpha()) else "EUR"

    return result


def _validate_agent4(raw: Optional[dict]) -> list:
    if not raw:
        return []
    items = raw.get("items") or []
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        desc = _str_or_none(item.get("description"))
        total = _float_or_none(item.get("total_price"))
        vat_rate = _float_or_none(item.get("vat_rate"))
        vat_amt = _float_or_none(item.get("vat_amount"))
        # Skip completely empty rows
        if not desc and total is None:
            continue
        result.append({
            "description": desc,
            "total_price": total,
            "vat_rate":    vat_rate if (vat_rate is not None and 0 <= vat_rate <= 100) else None,
            "vat_amount":  vat_amt,
        })
    return result


# ---------------------------------------------------------------------------
# Model builder
# ---------------------------------------------------------------------------

def _build_receipt_data(
    meta:         dict,
    counterparty: dict,
    amounts:      dict,
    items:        list,
    raw_text:     str,
    receipt_type: str,
) -> ReceiptData:

    # Counterparty
    cp: Optional[Counterparty] = None
    if counterparty:
        address = Address(
            street_and_number=  counterparty.get("street_and_number"),
            address_supplement= counterparty.get("address_supplement"),
            postcode=           counterparty.get("postcode"),
            city=               counterparty.get("city"),
            state=              counterparty.get("state"),
            country=            counterparty.get("country"),
        )
        cp = Counterparty(
            name=       counterparty.get("name"),
            vat_id=     counterparty.get("vat_id"),
            tax_number= counterparty.get("tax_number"),
            address=    address,
        )

    # Line items
    receipt_items: list[ReceiptItem] = []
    for idx, item in enumerate(items, start=1):
        try:
            receipt_items.append(ReceiptItem(
                description= item.get("description") or "",
                quantity=    None,
                unit_price=  None,
                total_price= parse_decimal(item.get("total_price")),
                vat_rate=    parse_decimal(item.get("vat_rate")),
                vat_amount=  parse_decimal(item.get("vat_amount")),
                category=    ReceiptCategory("other"),
                position=    idx,
            ))
        except Exception:
            pass

    return ReceiptData(
        raw_text=       raw_text,
        receipt_type=   ReceiptType(receipt_type),
        counterparty=   cp,
        receipt_number= meta.get("receipt_number"),
        receipt_date=   meta.get("receipt_date"),
        total_amount=   parse_decimal(amounts.get("total_amount")),
        vat_percentage= parse_decimal(amounts.get("vat_percentage")),
        vat_amount=     parse_decimal(amounts.get("vat_amount")),
        currency=       amounts.get("currency", "EUR"),
        category=       meta.get("category", ReceiptCategory("other")),
        items=          receipt_items,
    )


# ---------------------------------------------------------------------------
# Taxpayer-info cleanup
# ---------------------------------------------------------------------------

def _strip_taxpayer_fields(counterparty: dict, taxpayer_info: Optional[dict]) -> dict:
    """Silently null out counterparty fields that are exact copies of the taxpayer's
    own data (case-insensitive, whitespace-normalised).  No warnings are emitted.

    This guards against the LLM defaulting to the taxpayer's VAT-ID / tax-number
    / name when no real counterparty data is present in the document.
    """
    if not taxpayer_info:
        return counterparty

    def _norm(v: Optional[str]) -> str:
        return (v or "").strip().casefold()

    checks = {
        "name":               taxpayer_info.get("name"),
        "vat_id":             taxpayer_info.get("vat_id"),
        "tax_number":         taxpayer_info.get("tax_number"),
        # Address sub-fields — mapped from the individual taxpayer profile fields
        "street_and_number":  taxpayer_info.get("street"),
        "postcode":           taxpayer_info.get("postcode"),
        "city":               taxpayer_info.get("city"),
        "state":              taxpayer_info.get("state"),
        "country":            taxpayer_info.get("country"),
    }

    result = dict(counterparty)
    for field, taxpayer_value in checks.items():
        if taxpayer_value and _norm(result.get(field)) == _norm(taxpayer_value):
            result[field] = None

    return result


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    raw_text:      str,
    pdf_path:      Optional[Union[str, Path]],   # kept for API compat, not used
    receipt_type:  str,
    cfg:           Optional[AgentsConfig] = None,
    receipt_id:    Optional[str] = None,
    debug_root:    Optional[Path] = _DEFAULT_DEBUG_ROOT,
    taxpayer_info: Optional[dict] = None,
) -> ReceiptData:
    if cfg is None:
        cfg = AgentsConfig()

    agent_cfg = cfg.get_agent_config()

    debug_dir: Optional[Path] = None
    if debug_root is not None and receipt_id:
        debug_dir = Path(debug_root) / receipt_id
        debug_dir.mkdir(parents=True, exist_ok=True)

    # ── Agent 1: metadata ──────────────────────────────────────────────────
    _progress.emit(f"  {_ts()} → Agent 1: metadata")
    raw1 = call_llm(
        prompt=        build_agent1_prompt(raw_text),
        cfg=           agent_cfg,
        agent_name=    "agent1",
        expected_keys= ["receipt_number", "receipt_date", "category"],
        debug_dir=     debug_dir,
    )
    meta = _validate_agent1(raw1)

    # ── Agent 2: counterparty ──────────────────────────────────────────────
    _progress.emit(f"  {_ts()} → Agent 2: counterparty")
    raw2 = call_llm(
        prompt=        build_agent2_prompt(raw_text, receipt_type, taxpayer_info),
        cfg=           agent_cfg,
        agent_name=    "agent2",
        expected_keys= ["name", "vat_id", "tax_number", "street_and_number",
                        "address_supplement", "postcode", "city", "state", "country"],
        debug_dir=     debug_dir,
    )
    counterparty = _validate_agent2(raw2)
    counterparty = _strip_taxpayer_fields(counterparty, taxpayer_info)

    # ── Agent 3: amounts ───────────────────────────────────────────────────
    _progress.emit(f"  {_ts()} → Agent 3: amounts")
    raw3 = call_llm(
        prompt=        build_agent3_prompt(raw_text),
        cfg=           agent_cfg,
        agent_name=    "agent3",
        expected_keys= ["total_amount", "vat_percentage", "vat_amount", "currency"],
        debug_dir=     debug_dir,
    )
    amounts = _validate_agent3(raw3)

    # ── Agent 4: line items ────────────────────────────────────────────────
    _progress.emit(f"  {_ts()} → Agent 4: line items")
    raw4 = call_llm(
        prompt=        build_agent4_prompt(raw_text),
        cfg=           agent_cfg,
        agent_name=    "agent4",
        expected_keys= ["items"],
        debug_dir=     debug_dir,
    )
    items = _validate_agent4(raw4)

    # ── Debug: save final merge ────────────────────────────────────────────
    if debug_dir is not None:
        final_debug = {
            "meta":         {**meta, "receipt_date": str(meta.get("receipt_date", ""))},
            "counterparty": counterparty,
            "amounts":      amounts,
            "items":        items,
        }
        (debug_dir / "final.json").write_text(
            json.dumps(final_debug, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    return _build_receipt_data(meta, counterparty, amounts, items, raw_text, receipt_type)