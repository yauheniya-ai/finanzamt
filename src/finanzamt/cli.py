
import sys
import argparse
from importlib.metadata import version
from pathlib import Path
from finanzamt import FinanceAgent
from collections import defaultdict
from decimal import Decimal
import json

class FinanzamtCLI:
    def print_version(self):
        try:
            print(f"finanzamt version: {version('finanzamt')}")
        except Exception:
            print("finanzamt version: unknown")

    def process_receipt(self, file_stem, input_dir, output_dir=None, verbose=False):
        if verbose:
            print(f"[DEBUG] Processing file: {file_stem} in {input_dir}")
        agent = FinanceAgent()
        receipt_path = Path(input_dir) / f"{file_stem}.pdf"
        out_dir = Path(output_dir) if output_dir else Path(input_dir)
        output_path = out_dir / f"{file_stem}_extracted.json"
        result = agent.process_receipt(receipt_path)
        if result.success:
            print(f"Extraction successful!\nSaved to {output_path}")
            output_path.write_text(result.data.to_json(), encoding="utf-8")
        else:
            print(f"Extraction failed: {result.error_message}")

    def batch_process(self, input_dir, output_dir=None, verbose=False):
        agent = FinanceAgent()
        input_dir = Path(input_dir)
        out_dir = Path(output_dir) if output_dir else input_dir
        pdf_files = sorted(input_dir.glob("*.pdf"))
        if not pdf_files:
            print(f"No PDF files found in {input_dir.resolve()}")
            return
        out_dir.mkdir(parents=True, exist_ok=True)
        results = {}
        for pdf_path in pdf_files:
            if verbose:
                print(f"Processing {pdf_path.name}...")
            result = agent.process_receipt(pdf_path)
            results[str(pdf_path)] = result
            json_path = out_dir / f"{pdf_path.stem}_extracted.json"
            json_path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        # Print summary report
        successful = [r for r in results.values() if r.success]
        failed     = [r for r in results.values() if not r.success]
        total_amount = Decimal(0)
        total_vat = Decimal(0)
        by_category = defaultdict(Decimal)
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

def main():
    parser = argparse.ArgumentParser(
        description="finanzamt: Process scanned German receipt PDFs and extract structured data.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--version', action='store_true', help='Show package version and exit.')
    parser.add_argument('--file', default=None, metavar='STEM', help='Receipt filename without the .pdf extension.')
    parser.add_argument('--input-dir', default=None, metavar='DIR', help='Directory containing the receipt PDF(s).')
    parser.add_argument('--output-dir', default=None, metavar='DIR', help='Where to write the extracted JSON.')
    parser.add_argument('--batch', action='store_true', help='Batch process all PDFs in the input directory.')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output.')

    args = parser.parse_args()
    cli = FinanzamtCLI()

    if args.version:
        cli.print_version()
        return

    if args.batch and args.input_dir:
        cli.batch_process(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            verbose=args.verbose,
        )
        return

    if args.file and args.input_dir:
        cli.process_receipt(
            file_stem=args.file,
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            verbose=args.verbose,
        )
        return

    parser.print_help()

if __name__ == '__main__':
    main()
