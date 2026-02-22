"""
examples/batch_process.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Batch-process all PDF receipts in a directory and print a summary report.

Usage
-----
    # From the pypi/ directory:
    python -m examples.batch_process
    python -m examples.batch_process --input-dir examples/receipts --output-dir examples/results
    python -m examples.batch_process --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Dict

# Applications configure logging; libraries must not.
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    handlers=[logging.StreamHandler()],
)

from finanzamt import FinanceAgent
from finanzamt.models import ExtractionResult


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def process_receipts(
    input_dir: Path,
    output_dir: Path | None = None,
) -> Dict[str, ExtractionResult]:
    """
    Process all PDF receipts found in *input_dir*.

    Saves individual JSON result files to *output_dir* (defaults to
    *input_dir*) so results are available even if the run is interrupted.

    Returns a dict mapping ``str(pdf_path)`` → ``ExtractionResult``.
    """
    pdf_files = sorted(input_dir.glob("*.pdf"))
    if not pdf_files:
        logging.warning("No PDF files found in %s", input_dir.resolve())
        return {}

    out_dir = output_dir or input_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    logging.info("Found %d receipt(s) to process.", len(pdf_files))
    agent = FinanceAgent()
    results: Dict[str, ExtractionResult] = {}

    for pdf_path in pdf_files:
        logging.info("Processing %s …", pdf_path.name)
        result = agent.process_receipt(pdf_path)
        results[str(pdf_path)] = result

        # Persist individual result immediately
        json_path = out_dir / f"{pdf_path.stem}_extracted.json"
        json_path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def generate_report(results: Dict[str, ExtractionResult]) -> None:
    """Print a structured summary report to stdout."""
    if not results:
        print("No receipts processed.")
        return

    successful = [r for r in results.values() if r.success]
    failed     = [r for r in results.values() if not r.success]

    total_amount: Decimal = Decimal(0)
    total_vat:    Decimal = Decimal(0)
    by_category:  dict[str, Decimal] = defaultdict(Decimal)

    for result in successful:
        d = result.data
        if d.total_amount:
            total_amount += d.total_amount
        if d.vat_amount:
            total_vat += d.vat_amount
        if d.category:
            by_category[str(d.category)] += d.total_amount or Decimal(0)

    W = 50
    div  = "─" * W
    hdiv = "═" * W

    print(f"\n{hdiv}")
    print(f"  {'BATCH PROCESSING REPORT':^{W-4}}")
    print(hdiv)
    print(f"  Total receipts : {len(results)}")
    print(f"  Successful     : {len(successful)}")
    print(f"  Failed         : {len(failed)}")
    rate = len(successful) / len(results) if results else 0
    print(f"  Success rate   : {rate:.0%}")

    print(f"\n  {'FINANCIALS':^{W-4}}")
    print(div)
    print(f"  Total expenses : {total_amount:.2f} EUR")
    print(f"  Total VAT      : {total_vat:.2f} EUR")
    print(f"  Net (excl.VAT) : {total_amount - total_vat:.2f} EUR")

    if by_category:
        print(f"\n  {'BY CATEGORY':^{W-4}}")
        print(div)
        for cat, amt in sorted(by_category.items(), key=lambda x: -x[1]):
            print(f"  {cat:<22} {amt:>10.2f} EUR")

    print(f"\n  {'DETAIL':^{W-4}}")
    print(div)
    for path, result in results.items():
        name = Path(path).name
        if result.success:
            d = result.data
            amt = f"{d.total_amount:.2f} EUR" if d.total_amount else "—"
            date = d.receipt_date.date() if d.receipt_date else "—"
            vat  = f"{d.vat_percentage}%" if d.vat_percentage else "—"
            t    = f"{result.processing_time:.1f}s" if result.processing_time else ""
            print(f"\n  ✓  {name}  ({t})")
            print(f"     Vendor   : {d.vendor or '—'}")
            print(f"     Date     : {date}")
            print(f"     Total    : {amt}  VAT: {vat}")
            print(f"     Category : {d.category}")
            print(f"     Items    : {len(d.items)}")
        else:
            print(f"\n  ✗  {name}")
            print(f"     Error: {result.error_message}")

    print(f"\n{hdiv}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Batch-process German receipt PDFs with finanzamt.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input-dir",
        default="examples/receipts",
        metavar="DIR",
        help="Directory containing receipt PDF files.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        metavar="DIR",
        help="Directory for JSON result files (defaults to --input-dir).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else None

    if not input_dir.exists():
        logging.error("Input directory not found: %s", input_dir)
        return 1

    try:
        results = process_receipts(input_dir, output_dir)
        generate_report(results)
        failed = sum(1 for r in results.values() if not r.success)
        return 1 if failed else 0
    except Exception:
        logging.exception("Batch processing failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())