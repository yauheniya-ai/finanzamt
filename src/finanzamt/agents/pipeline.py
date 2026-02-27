"""
finanzamt.agents.pipeline
~~~~~~~~~~~~~~~~~~~~~~~~~~
Orchestrates the full multi-agent extraction pipeline.

  Step 0: Create debug directory   ~/.finanzamt/debug/<receipt_id>/
  Step 1: Rule-based extractor  →  00_rules_input.txt / 00_rules_output.json
  Step 2: Agent 1 (text LLM)    →  01_agent1_prompt.txt / 01_agent1_raw_response.txt / 01_agent1_parsed.json
  Step 3: Agent 2 (vision LLM)  →  02_agent2_prompt.txt / 02_agent2_input.png / 02_agent2_raw_response.txt / 02_agent2_parsed.json
  Step 4: Agent 3 (Validator)   →  03_agent3_prompt.txt / 03_agent3_raw_response.txt / 03_agent3_parsed.json
  Step 5: Final ReceiptData     →  04_final.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Union

from ..models import (
    Address, Counterparty,
    ReceiptCategory, ReceiptData, ReceiptItem, ReceiptType,
)
from ..utils import parse_date, parse_decimal
from . import agent1_text, agent2_vision, agent3_validator
from .config import AgentsConfig
from .rules import RulesResult, run_rules

# Default debug root: ~/.finanzamt/debug/
_DEFAULT_DEBUG_ROOT = Path.home() / ".finanzamt" / "debug"

# ---------------------------------------------------------------------------
# Label sanitisation
# ---------------------------------------------------------------------------

_LABEL_SUFFIXES = (":", "nr.:", "nummer:", "datum:", "betrag:", "summe:")
_LABEL_WORDS = frozenset([
    "kundennr", "rechnungsnr", "rechnungsnummer", "rechnungsdatum",
    "bestellnr", "lieferschein", "auftragsnr", "steuer-nr",
    "steuernummer", "ust-idnr", "mwst-nr", "telefon", "telefax",
    "e-mail", "email", "web", "www", "iban", "bic", "konto",
])


def _sanitize_name(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip()
    lower = v.lower()
    if lower.endswith(":") or any(lower.endswith(s) for s in _LABEL_SUFFIXES):
        return None
    if lower.rstrip(":").rstrip(".") in _LABEL_WORDS:
        return None
    return v if len(v) >= 2 else None


# ---------------------------------------------------------------------------
# Model construction
# ---------------------------------------------------------------------------

def _build_receipt_data(data: dict, raw_text: str, receipt_type: str) -> ReceiptData:
    addr_raw = data.get("counterparty_address") or {}
    address = Address(
        street=        addr_raw.get("street"),
        street_number= addr_raw.get("street_number"),
        postcode=      addr_raw.get("postcode"),
        city=          addr_raw.get("city"),
        country=       addr_raw.get("country"),
    )
    cp_name = _sanitize_name(data.get("counterparty_name"))
    counterparty: Optional[Counterparty] = None
    if cp_name or any(vars(address).values()):
        counterparty = Counterparty(
            name=       cp_name,
            address=    address,
            tax_number= data.get("counterparty_tax_number"),
            vat_id=     data.get("counterparty_vat_id"),
        )

    items: list[ReceiptItem] = []
    for item_data in data.get("items") or []:
        try:
            items.append(ReceiptItem(
                description= item_data.get("description", ""),
                quantity=    parse_decimal(item_data.get("quantity")),
                unit_price=  parse_decimal(item_data.get("unit_price")),
                total_price= parse_decimal(item_data.get("total_price")),
                category=    ReceiptCategory(item_data.get("category", "other")),
                vat_rate=    parse_decimal(item_data.get("vat_rate")),
            ))
        except Exception:  # noqa: BLE001
            pass

    rtype = receipt_type if receipt_type != "purchase" else str(
        data.get("receipt_type") or receipt_type
    )
    raw_date = data.get("receipt_date")

    return ReceiptData(
        raw_text=       raw_text,
        receipt_type=   ReceiptType(rtype),
        counterparty=   counterparty,
        receipt_number= data.get("receipt_number"),
        receipt_date=   parse_date(raw_date) if raw_date else None,
        total_amount=   parse_decimal(data.get("total_amount")),
        vat_percentage= parse_decimal(data.get("vat_percentage")),
        vat_amount=     parse_decimal(data.get("vat_amount")),
        category=       ReceiptCategory(data.get("category", "other")),
        items=          items,
    )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    raw_text:     str,
    pdf_path:     Optional[Union[str, Path]],
    receipt_type: str,
    cfg:          Optional[AgentsConfig] = None,
    receipt_id:   Optional[str] = None,
    debug_root:   Optional[Path] = _DEFAULT_DEBUG_ROOT,
) -> ReceiptData:
    """
    Run the full extraction pipeline.

    Saves every step's input and output to:
      debug_root / <receipt_id> /
        00_rules_input.txt
        00_rules_output.json
        01_agent1_prompt.txt
        01_agent1_raw_response.txt
        01_agent1_parsed.json
        02_agent2_prompt.txt
        02_agent2_input.png
        02_agent2_raw_response.txt
        02_agent2_parsed.json
        03_agent3_prompt.txt
        03_agent3_raw_response.txt
        03_agent3_parsed.json
        04_final.json

    Pass debug_root=None to disable file output entirely.
    """
    if cfg is None:
        cfg = AgentsConfig()

    # Create per-receipt debug directory
    debug_dir: Optional[Path] = None
    if debug_root is not None and receipt_id:
        debug_dir = Path(debug_root) / receipt_id
        debug_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Rules ──────────────────────────────────────────────────
    rules: RulesResult = run_rules(raw_text, receipt_type, debug_dir=debug_dir)
    hints: dict = rules.to_dict()

    # ── Step 2: Agent 1 (text) ─────────────────────────────────────────
    json1 = agent1_text.run(
        text=raw_text,
        hints=hints,
        cfg=cfg.get_agent1_config(),
        debug_dir=debug_dir,
    )

    # ── Step 3: Agent 2 (vision) ───────────────────────────────────────
    json2: Optional[dict] = None
    if pdf_path is not None:
        json2 = agent2_vision.run(
            pdf_path=pdf_path,
            cfg=cfg.get_agent2_config(),
            debug_dir=debug_dir,
        )

    # ── Step 4: Agent 3 (Validator) ────────────────────────────────────
    json3 = agent3_validator.run(
        json1=json1,
        json2=json2,
        cfg=cfg.get_agent3_config(),
        debug_dir=debug_dir,
    )

    # ── Step 5: Build ReceiptData ──────────────────────────────────────
    # Fallback chain: json3 → json1 → json2 → hints (rules)
    final = json3 or json1 or json2 or hints

    if debug_dir is not None:
        source = (
            "agent3_validator" if json3 else
            "agent1_text"      if json1 else
            "agent2_vision"    if json2 else
            "rules_fallback"
        )
        summary = {**final, "_source": source}
        (debug_dir / "04_final.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return _build_receipt_data(final, raw_text, receipt_type)