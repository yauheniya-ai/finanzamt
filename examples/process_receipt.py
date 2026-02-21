from pathlib import Path
from finanzamt import FinanceAgent

def process_receipt(file_stem: str, input_dir: Path = Path("examples/receipts")):
    """Process a single receipt and save results."""
    agent = FinanceAgent()
    receipt_path = input_dir / f"{file_stem}.pdf"
    output_path = input_dir / f"{file_stem}_extracted_data.json"

    result = agent.process_receipt(receipt_path)
    
    if result.success:
        print("Extraction successful!")
        print(f"Company: {result.data.company}")
        print(f"Date: {result.data.date}")
        print(f"Total Amount: {result.data.amount_euro} EUR")
        print(f"VAT: {result.data.vat_percentage}%")
        
        print("\nItems:")
        for item in result.data.items:
            print(f"- {item.description}: {item.total_price} EUR ({item.category.value})")
        
        output_path.write_text(result.data.to_json())
        print(f"\nSaved to {output_path}")
    else:
        print(f"Error: {result.error_message}")

if __name__ == "__main__":
    # Configurable at runtime
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="receipt1", help="Receipt file name without extension")
    parser.add_argument("--input-dir", default="examples/receipts", help="Directory containing receipts")
    args = parser.parse_args()
    
    process_receipt(
        file_stem=args.file,
        input_dir=Path(args.input_dir)
    )