"""
examples/process_receipt.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Process a single receipt PDF. Results are automatically saved to the local DB.

Usage
-----
    python -m examples.process_receipt
    python -m examples.process_receipt --file receipt1 --input-dir examples/receipts
    python -m examples.process_receipt --file invoice1 --type sale
    python -m examples.process_receipt --output-dir results/     # also save JSON
    python -m examples.process_receipt --db /tmp/test.db
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(name)s — %(message)s")

from finanzamt import FinanceAgent
from finanzamt.storage.sqlite import DEFAULT_DB_PATH


def process_receipt(
    file_stem: str,
    input_dir: Path = Path("examples/receipts"),
    output_dir: Path | None = None,
    db_path: Path | None = None,       # None → use default ~/.finanzamt/receipts.db
    no_db: bool = False,               # True → disable persistence entirely
    receipt_type: str = "purchase",
) -> bool:
    receipt_path = input_dir / f"{file_stem}.pdf"
    if not receipt_path.exists():
        print(f"[error] File not found: {receipt_path}", file=sys.stderr)
        return False

    print(f"Processing: {receipt_path}")

    # db_path=None → disabled; explicit path or DEFAULT_DB_PATH → persist
    resolved_db = None if no_db else (db_path if db_path else DEFAULT_DB_PATH)
    agent = FinanceAgent(db_path=resolved_db)
    result = agent.process_receipt(receipt_path, receipt_type=receipt_type)

    if result.duplicate:
        print(f"\n  ⚠  Duplicate detected — this receipt was already processed.")
        print(f"     Existing ID : {result.existing_id}")
        print(f"     Vendor      : {result.data.counterparty.name if result.data and result.data.counterparty else '—'}")
        print(f"     No changes made to the database.\n")
        return True

    if not result.success:
        print(f"[error] Extraction failed: {result.error_message}", file=sys.stderr)
        return False

    data = result.data

    # ------------------------------------------------------------------
    # Print summary
    # ------------------------------------------------------------------
    W = 44
    print("\n" + "─" * W)
    print(f"  {'EXTRACTION RESULT':^{W - 4}}")
    print("─" * W)

    cp = data.counterparty

    def row(label: str, value: object) -> None:
        print(f"  {label:<18} {str(value) if value is not None else '—'}")

    row("Type",         str(data.receipt_type).upper())
    row("Counterparty", cp.name if cp else None)
    if cp and cp.address:
        row("Address",  str(cp.address))
    if cp and cp.vat_id:
        row("VAT ID",   cp.vat_id)
    row("Receipt #",    data.receipt_number)
    row("Date",         data.receipt_date.date() if data.receipt_date else None)
    row("Category",     str(data.category))
    print("  " + "·" * (W - 4))
    row("Total",        f"{data.total_amount} EUR"   if data.total_amount   else None)
    row("VAT %",        f"{data.vat_percentage} %"   if data.vat_percentage else None)
    row("VAT amount",   f"{data.vat_amount} EUR"     if data.vat_amount     else None)
    row("Net",          f"{data.net_amount} EUR"     if data.net_amount     else None)

    if data.items:
        print("  " + "·" * (W - 4))
        print(f"  {'Items':<18}")
        for item in data.items:
            price = f"{item.total_price} EUR" if item.total_price else "—"
            print(f"    • {item.description[:28]:<28}  {price}  [{item.category}]")

    print("─" * W)
    print(f"  Processing time : {result.processing_time:.2f}s")
    print(f"  ID (hash)       : {data.id[:16]}…")

    if no_db:
        print("  DB persistence  : disabled")
    else:
        db_display = db_path or "~/.finanzamt/receipts.db"
        print(f"  Saved to DB     : {db_display}")

    # ------------------------------------------------------------------
    # Optionally save JSON
    # ------------------------------------------------------------------
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"{file_stem}_extracted.json"
        out_path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"  Saved JSON      : {out_path}")

    print()
    return True


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Process a German receipt PDF (auto-saves to DB).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--file",       default="receipt1",         metavar="STEM")
    p.add_argument("--input-dir",  default="examples/receipts", metavar="DIR")
    p.add_argument("--output-dir", default=None,               metavar="DIR",
                   help="Also write extracted JSON here (optional).")
    p.add_argument("--type",       default="purchase",         choices=["purchase", "sale"],
                   help="purchase = Eingangsrechnung; sale = Ausgangsrechnung.")
    p.add_argument("--db",         default=None,               metavar="FILE",
                   help="SQLite DB path (default: ~/.finanzamt/receipts.db).")
    p.add_argument("--no-db",      action="store_true",
                   help="Disable DB persistence (JSON extraction only).")
    p.add_argument("--verbose", "-v", action="store_true")
    return p


if __name__ == "__main__":
    args = _build_parser().parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    ok = process_receipt(
        file_stem=args.file,
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir) if args.output_dir else None,
        db_path=Path(args.db) if args.db else None,
        no_db=args.no_db,
        receipt_type=args.type,
    )
    sys.exit(0 if ok else 1)