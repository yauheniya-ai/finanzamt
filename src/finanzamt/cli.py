"""
finanzamt.cli
~~~~~~~~~~~~~
Command-line interface for finanzamt.

Entry point registered in pyproject.toml::

    [project.scripts]
    finanzamt = "finanzamt.cli:main"

Usage examples
--------------
    finanzamt --version

    # Single receipt
    finanzamt --file receipt1 --input-dir receipts/

    # Batch
    finanzamt --batch --input-dir receipts/ --output-dir results/

    # Scan receipts into local DB, then generate Q1 UStVA report
    finanzamt --ustva --input-dir receipts/ --quarter 1 --year 2024

    # Generate report from already-stored receipts
    finanzamt --ustva --quarter 1 --year 2024 --output ustva_q1.json

    # Use a custom DB path
    finanzamt --ustva --input-dir receipts/ --db /tmp/mydb.db
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path

from finanzamt import FinanceAgent
from finanzamt.storage.sqlite import DEFAULT_DB_PATH
from finanzamt.storage import get_repository
from finanzamt.tax.ustva import generate_ustva


# ---------------------------------------------------------------------------
# CLI class
# ---------------------------------------------------------------------------

class FinanzamtCLI:

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def print_version(self) -> None:
        try:
            print(f"finanzamt version: {version('finanzamt')}")
        except Exception:
            print("finanzamt version: unknown")

    # ------------------------------------------------------------------
    # Single receipt
    # ------------------------------------------------------------------

    def process_receipt(
        self,
        file_stem: str,
        input_dir: str | Path,
        output_dir: str | Path | None = None,
        verbose: bool = False,
        receipt_type: str = "purchase",
        db_path: Path | None = None,
        no_db: bool = False,
    ) -> int:
        """Process one receipt PDF. DB save is automatic. Returns exit code."""
        receipt_path = Path(input_dir) / f"{file_stem}.pdf"
        if not receipt_path.exists():
            print(f"[error] File not found: {receipt_path}", file=sys.stderr)
            return 1

        if verbose:
            print(f"Processing: {receipt_path}")

        agent = FinanceAgent(db_path=None if no_db else (db_path if db_path else DEFAULT_DB_PATH))
        result = agent.process_receipt(receipt_path, receipt_type=receipt_type)

        if result.duplicate:
            d = result.data
            cp = d.counterparty.name if d and d.counterparty else "—"
            print(f"⚠  Duplicate — already in DB: {cp}  (id: {result.existing_id[:16]}…)")
            return 0

        if result.success:
            d = result.data
            cp = d.counterparty.name if d.counterparty else "—"
            print(f"✓  {str(d.receipt_type).upper()}  {cp}  {d.total_amount} EUR")
            if output_dir:
                out_dir = Path(output_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
                out = out_dir / f"{file_stem}_extracted.json"
                out.write_text(result.data.to_json(), encoding="utf-8")
                print(f"   JSON → {out}")
            return 0
        else:
            print(f"✗  Extraction failed: {result.error_message}", file=sys.stderr)
            return 1

    # ------------------------------------------------------------------
    # Batch
    # ------------------------------------------------------------------

    def batch_process(
        self,
        input_dir: str | Path,
        output_dir: str | Path | None = None,
        verbose: bool = False,
        receipt_type: str = "purchase",
        db_path: Path | None = None,
        no_db: bool = False,
    ) -> int:
        """Batch-process all PDFs. DB save is automatic. Returns exit code."""
        input_dir = Path(input_dir)
        out_dir   = Path(output_dir) if output_dir else None
        pdf_files = sorted(input_dir.glob("*.pdf"))

        if not pdf_files:
            print(f"No PDF files found in {input_dir.resolve()}")
            return 1

        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)

        agent   = FinanceAgent(db_path=None if no_db else (db_path if db_path else DEFAULT_DB_PATH))
        results = {}

        for pdf_path in pdf_files:
            if verbose:
                print(f"Processing {pdf_path.name} ...")
            result = agent.process_receipt(pdf_path, receipt_type=receipt_type)
            results[str(pdf_path)] = result
            if out_dir:
                json_path = out_dir / f"{pdf_path.stem}_extracted.json"
                json_path.write_text(
                    json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

        self._print_batch_report(results)
        failed = sum(1 for r in results.values() if not r.success and not r.duplicate)
        return 1 if failed else 0

    def _print_batch_report(self, results: dict) -> None:
        successful = [r for r in results.values() if r.success and not r.duplicate]
        duplicates = [r for r in results.values() if r.duplicate]
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

        W    = 50
        div  = "─" * W
        hdiv = "═" * W
        rate = len(successful) / len(results) if results else 0

        print(f"\n{hdiv}")
        print(f"  {'BATCH PROCESSING REPORT':^{W - 4}}")
        print(hdiv)
        print(f"  Total receipts : {len(results)}")
        print(f"  Newly saved    : {len(successful)}")
        print(f"  Duplicates     : {len(duplicates)}")
        print(f"  Failed         : {len(failed)}")
        print(f"  Success rate   : {rate:.0%}")
        print(f"\n  {'FINANCIALS (new only)':^{W - 4}}")
        print(div)
        print(f"  Total expenses : {total_amount:.2f} EUR")
        print(f"  Total VAT      : {total_vat:.2f} EUR")
        print(f"  Net (excl.VAT) : {total_amount - total_vat:.2f} EUR")

        if by_category:
            print(f"\n  {'BY CATEGORY':^{W - 4}}")
            print(div)
            for cat, amt in sorted(by_category.items(), key=lambda x: -x[1]):
                print(f"  {cat:<22} {amt:>10.2f} EUR")

        print(f"\n  {'DETAIL':^{W - 4}}")
        print(div)
        for path, result in results.items():
            name = Path(path).name
            if result.duplicate:
                print(f"\n  ⚠  {name}  [duplicate — skipped]")
            elif result.success:
                d   = result.data
                amt = f"{d.total_amount:.2f} EUR" if d.total_amount else "—"
                dt  = d.receipt_date.date() if d.receipt_date else "—"
                vat = f"{d.vat_percentage}%" if d.vat_percentage else "—"
                t   = f"{result.processing_time:.1f}s" if result.processing_time else ""
                cp  = d.counterparty.name if d.counterparty else "—"
                print(f"\n  ✓  {name}  ({t})")
                print(f"     {str(d.receipt_type).upper():<10}  {cp}")
                print(f"     Date    : {dt}   Total: {amt}   VAT: {vat}")
                print(f"     Category: {d.category}   Items: {len(d.items)}")
            else:
                print(f"\n  ✗  {name}")
                print(f"     Error: {result.error_message}")

        print(f"\n{hdiv}\n")

    # ------------------------------------------------------------------
    # UStVA
    # ------------------------------------------------------------------

    @staticmethod
    def _quarter_bounds(quarter: int, year: int) -> tuple[date, date]:
        starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
        ends   = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
        ms, ds = starts[quarter]
        me, de = ends[quarter]
        return date(year, ms, ds), date(year, me, de)

    def ingest_receipts(
        self,
        input_dir: Path,
        db_path: Path | None = None,
        verbose: bool = False,
        receipt_type: str = "purchase",
    ) -> int:
        """Scan PDFs and auto-save to DB. Returns number saved."""
        pdf_files = sorted(input_dir.glob("*.pdf"))
        if not pdf_files:
            print(f"No PDF files found in {input_dir.resolve()}")
            return 0

        agent = FinanceAgent(db_path=db_path if db_path else DEFAULT_DB_PATH)
        saved = 0
        dupes = 0

        for pdf in pdf_files:
            if verbose:
                print(f"  {pdf.name} ...", end=" ", flush=True)
            result = agent.process_receipt(pdf, receipt_type=receipt_type)
            if result.duplicate:
                dupes += 1
                if verbose:
                    print("DUPLICATE (skipped)")
            elif result.success:
                saved += 1
                if verbose:
                    d  = result.data
                    cp = d.counterparty.name if d.counterparty else "unknown"
                    print(f"OK  ({cp}, {d.total_amount} EUR)")
            else:
                if verbose:
                    print(f"FAILED — {result.error_message}")

        print(f"{saved} saved, {dupes} duplicates skipped (of {len(pdf_files)} total).")
        return saved

    def run_ustva(
        self,
        quarter: int,
        year: int,
        db_path: Path | None = None,
        output: Path | None = None,
        output_dir: Path | None = None,
    ) -> int:
        """
        Generate and print a UStVA report for the given quarter.

        Args:
            output:     Explicit output file path. Takes priority over output_dir.
            output_dir: Directory to write an auto-named file
                        (e.g. ``ustva_q1_2024.json``).
        """
        start, end = self._quarter_bounds(quarter, year)

        with get_repository(db_path) as repo:
            receipts = list(repo.find_by_period(start, end))

        if not receipts:
            print(
                f"No receipts found for Q{quarter} {year}.\n"
                f"Run with --input-dir to scan and store PDFs first."
            )
            return 1

        report = generate_ustva(receipts, start, end)
        print(report.summary())

        # Resolve output path: explicit --output beats --output-dir auto-name
        out_path: Path | None = None
        if output:
            out_path = output
        elif output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            out_path = output_dir / f"ustva_q{quarter}_{year}.json"

        if out_path:
            report.to_json(out_path)
            print(f"Report saved to {out_path}")

        return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="finanzamt: process German receipts and prepare tax returns.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--version", action="store_true",
        help="Show package version and exit.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose output.",
    )

    # -- Receipt processing -----------------------------------------------
    receipt_group = parser.add_argument_group("Receipt processing")
    receipt_group.add_argument(
        "--file", default=None, metavar="STEM",
        help="Receipt filename without the .pdf extension.",
    )
    receipt_group.add_argument(
        "--input-dir", default=None, metavar="DIR",
        help="Directory containing the receipt PDF(s).",
    )
    receipt_group.add_argument(
        "--output-dir", default=None, metavar="DIR",
        help="Where to write the extracted JSON file(s).",
    )
    receipt_group.add_argument(
        "--batch", action="store_true",
        help="Batch process all PDFs in --input-dir.",
    )
    receipt_group.add_argument(
        "--type", default="purchase", choices=["purchase", "sale"],
        help="purchase = Eingangsrechnung (you paid); sale = Ausgangsrechnung (client paid you).",
    )
    receipt_group.add_argument(
        "--no-db", action="store_true",
        help="Disable DB persistence (extraction + JSON only).",
    )

    # -- Tax return -------------------------------------------------------
    tax_group = parser.add_argument_group("UStVA tax return")
    tax_group.add_argument(
        "--ustva", action="store_true",
        help="Generate a UStVA (VAT pre-return) report.",
    )
    tax_group.add_argument(
        "--quarter", type=int, default=1, choices=[1, 2, 3, 4],
        help="Fiscal quarter for the UStVA report.",
    )
    tax_group.add_argument(
        "--year", type=int, default=date.today().year,
        help="Fiscal year for the UStVA report.",
    )
    tax_group.add_argument(
        "--output", default=None, metavar="FILE",
        help=(
            "Write UStVA JSON report to this explicit file path. "
            "If omitted and --output-dir is set, the file is named "
            "automatically, e.g. ustva_q1_2024.json."
        ),
    )
    tax_group.add_argument(
        "--db", default=None, metavar="FILE",
        help="SQLite database path (default: ~/.finanzamt/finanzamt.db).",
    )

    # -- Web UI -----------------------------------------------------------
    ui_group = parser.add_argument_group("Web UI")
    ui_group.add_argument(
        "--ui", action="store_true",
        help="Start the web UI server (requires: pip install finanzamt[ui]).",
    )
    ui_group.add_argument(
        "--host", default="127.0.0.1", metavar="HOST",
        help="UI server bind address.",
    )
    ui_group.add_argument(
        "--port", default=8000, type=int, metavar="PORT",
        help="UI server port.",
    )
    ui_group.add_argument(
        "--no-browser", action="store_true",
        help="Do not open the browser when starting the UI.",
    )
    ui_group.add_argument(
        "--reload", action="store_true",
        help="Enable hot-reload (development mode).",
    )
    ui_group.add_argument(
        "--log-level",
        default="warning",
        choices=["debug", "info", "warning", "error"],
        metavar="LEVEL",
        help="Log level for the UI server (debug, info, warning, error). Default: warning.",
    )

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = _build_parser()
    args   = parser.parse_args()
    cli    = FinanzamtCLI()

    if args.verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(levelname)-8s %(name)s — %(message)s",
        )

    if args.version:
        cli.print_version()
        return 0

    db_path = Path(args.db) if args.db else None
    no_db   = getattr(args, "no_db", False)

    # -- UStVA flow -------------------------------------------------------
    if args.ustva:
        if args.input_dir:
            cli.ingest_receipts(
                input_dir=Path(args.input_dir),
                db_path=db_path,
                verbose=args.verbose,
                receipt_type=args.type,
            )
        return cli.run_ustva(
            quarter=args.quarter,
            year=args.year,
            db_path=db_path,
            output=Path(args.output) if args.output else None,
            output_dir=Path(args.output_dir) if args.output_dir else None,
        )

    # -- Batch processing -------------------------------------------------
    if args.batch and args.input_dir:
        return cli.batch_process(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            verbose=args.verbose,
            receipt_type=args.type,
            db_path=db_path,
            no_db=no_db,
        )

    # -- Single receipt ---------------------------------------------------
    if args.file and args.input_dir:
        return cli.process_receipt(
            file_stem=args.file,
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            verbose=args.verbose,
            receipt_type=args.type,
            db_path=db_path,
            no_db=no_db,
        )

    # -- Web UI ----------------------------------------------------------
    if args.ui:
        from finanzamt.ui.server import launch
        launch(
            host=args.host,
            port=args.port,
            reload=args.reload,
            open_browser=not args.no_browser,
            log_level=args.log_level,
        )
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())