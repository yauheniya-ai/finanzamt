"""
examples/process_receipt.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Example script: process a single receipt PDF and print + save the results.

Usage
-----
    # From the pypi/ directory:
    python -m examples.process_receipt
    python -m examples.process_receipt --file receipt1 --input-dir examples/receipts
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Applications (not libraries) should configure logging.
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s  %(name)s — %(message)s",
)

from finanzamt import FinanceAgent


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def process_receipt(
    file_stem: str,
    input_dir: Path = Path("examples/receipts"),
    output_dir: Path | None = None,
) -> bool:
    """
    Process a single receipt PDF and write the extracted data to JSON.

    Args:
        file_stem:  Filename without extension (e.g. ``"receipt1"``).
        input_dir:  Directory that contains the PDF.
        output_dir: Where to write the JSON result. Defaults to ``input_dir``.

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    receipt_path = input_dir / f"{file_stem}.pdf"
    out_dir = output_dir or input_dir
    output_path = out_dir / f"{file_stem}_extracted.json"

    if not receipt_path.exists():
        print(f"[error] Receipt not found: {receipt_path}", file=sys.stderr)
        return False

    print(f"Processing: {receipt_path}")
    agent = FinanceAgent()
    result = agent.process_receipt(receipt_path)

    if not result.success:
        print(f"[error] Extraction failed: {result.error_message}", file=sys.stderr)
        return False

    data = result.data

    # ------------------------------------------------------------------
    # Print summary
    # ------------------------------------------------------------------
    width = 44
    print("\n" + "─" * width)
    print(f"  {'EXTRACTION RESULT':^{width - 4}}")
    print("─" * width)

    def row(label: str, value: object) -> None:
        display = str(value) if value is not None else "—"
        print(f"  {label:<18} {display}")

    row("Vendor",       data.vendor)
    row("Address",      data.vendor_address)
    row("Receipt #",    data.receipt_number)
    row("Date",         data.receipt_date.date() if data.receipt_date else None)
    row("Category",     str(data.category))
    print("  " + "·" * (width - 4))
    row("Total",        f"{data.total_amount} EUR" if data.total_amount else None)
    row("VAT %",        f"{data.vat_percentage} %" if data.vat_percentage else None)
    row("VAT amount",   f"{data.vat_amount} EUR"   if data.vat_amount    else None)
    row("Net",          f"{data.net_amount} EUR"    if data.net_amount    else None)

    if data.items:
        print("  " + "·" * (width - 4))
        print(f"  {'Items':<18}")
        for item in data.items:
            price = f"{item.total_price} EUR" if item.total_price else "—"
            print(f"    • {item.description[:28]:<28}  {price}  [{item.category}]")

    print("─" * width)
    print(f"  Processing time: {result.processing_time:.2f}s")

    # ------------------------------------------------------------------
    # Save JSON
    # ------------------------------------------------------------------
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  Saved → {output_path}\n")
    return True


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Process a scanned German receipt PDF with finanzamt.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--file",
        default="receipt1",
        metavar="STEM",
        help="Receipt filename without the .pdf extension.",
    )
    parser.add_argument(
        "--input-dir",
        default="examples/receipts",
        metavar="DIR",
        help="Directory containing the receipt PDF.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        metavar="DIR",
        help="Where to write the extracted JSON (defaults to --input-dir).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    return parser


if __name__ == "__main__":
    args = _build_parser().parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    success = process_receipt(
        file_stem=args.file,
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )
    sys.exit(0 if success else 1)