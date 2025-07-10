from pathlib import Path
from finance_agent import FinanceAgent
import logging
from typing import Dict
from finance_agent.models import ExtractionResult

def configure_logging():
    """Set up basic logging configuration"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler()
        ]
    )

def process_receipts(input_dir: Path) -> Dict[str, ExtractionResult]:
    """
    Process all PDF receipts in a directory
    Args:
        input_dir: Path to directory containing receipt PDFs
    Returns:
        Dictionary mapping file paths to extraction results
    """
    agent = FinanceAgent()
    pdf_files = list(input_dir.glob("*.pdf"))
    
    if not pdf_files:
        logging.warning(f"No PDF files found in {input_dir.resolve()}")
        return {}
    
    logging.info(f"Found {len(pdf_files)} receipts to process")
    return agent.batch_process(pdf_files)

def generate_report(results: Dict[str, ExtractionResult]) -> None:
    """Generate a summary report of processing results"""
    successful = sum(1 for r in results.values() if r.success)
    
    print(f"\n{' Processing Report ':=^40}")
    print(f"Total receipts: {len(results)}")
    print(f"Successful: {successful}")
    print(f"Failed: {len(results) - successful}")
    print(f"Success rate: {successful/len(results):.1%}" if results else "N/A")
    
    for path, result in results.items():
        filename = Path(path).name
        if result.success:
            print(f"\n✓ {filename}")
            print(f"  Merchant: {result.data.company}")
            print(f"  Date: {result.data.date}")
            print(f"  Amount: {result.data.amount_euro}€")
            print(f"  Items: {len(result.data.items)}")
        else:
            print(f"\n✗ {filename}: {result.error_message}")

def main():
    configure_logging()
    
    try:
        receipt_dir = Path("./examples/receipts").resolve()
        if not receipt_dir.exists():
            raise FileNotFoundError(f"Directory not found: {receipt_dir}")
            
        results = process_receipts(receipt_dir)
        generate_report(results)
        
    except Exception as e:
        logging.error(f"Processing failed: {str(e)}", exc_info=True)
        return 1
    
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())