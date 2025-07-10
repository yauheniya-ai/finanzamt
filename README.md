# AI Finance Agent 

An intelligent agentic AI library for processing financial receipts and extracting structured data.

## Features

- **OCR Processing**: Extract text from PDF receipts using advanced OCR
- **LLM Integration**: Uses local Ollama models for intelligent data extraction
- **German Receipt Support**: Specialized for German receipt formats
- **Structured Output**: Extracts company, date, amounts, and VAT information
- **Fallback Processing**: Rule-based extraction when LLM fails
- **Batch Processing**: Handle multiple receipts efficiently

## Installation

```bash
pip install ai-finance-agent
```

### System Requirements

- Python 3.8+
- Tesseract OCR installed on your system
- Ollama running locally (optional but recommended)

#### Install Tesseract OCR

**Ubuntu/Debian:**
```bash
sudo apt-get install tesseract-ocr tesseract-ocr-deu
```

**macOS:**
```bash
brew install tesseract tesseract-lang
```

**Windows:**
Download from: https://github.com/UB-Mannheim/tesseract/wiki

#### Install Ollama

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a vision model
ollama pull llama3.2-vision
```

## Quick Start


```python
from finance_agent import FinanceAgent

# Initialize the agent
agent = FinanceAgent()

# Process a receipt
result = agent.process_receipt("receipt.pdf")

if result.success:
    print(f"Company: {result.data.company}")
    print(f"Date: {result.data.date}")
    print(f"Amount: {result.data.amount_euro} EUR")
    print(f"VAT: {result.data.vat_percentage}% ({result.data.vat_euro} EUR)")
    
    # Save as JSON
    with open("extracted_data.json", "w") as f:
        f.write(result.data.to_json())
else:
    print(f"Processing failed: {result.error_message}")
```

## Configuration

```python
from finance_agent import FinanceAgent, Config

# Custom configuration
config = Config()
config.OLLAMA_BASE_URL = "http://localhost:11434"
config.DEFAULT_MODEL = "llama3.2-vision"
config.OCR_LANGUAGE = "deu+eng"

agent = FinanceAgent(config=config)
```

## API Reference

### FinanceAgent

The main class for processing receipts.

#### Methods

- `process_receipt(pdf_path: Union[str, Path, bytes]) -> ExtractionResult`
- `batch_process(pdf_paths: List[Union[str, Path]]) -> Dict[str, ExtractionResult]`

### ReceiptData

Data model for extracted receipt information.

#### Attributes

- `company: Optional[str]` - Company name
- `date: Optional[datetime]` - Receipt date
- `amount_euro: Optional[Decimal]` - Total amount in EUR
- `vat_percentage: Optional[Decimal]` - VAT percentage
- `vat_euro: Optional[Decimal]` - VAT amount in EUR
- `confidence_score: Optional[float]` - Extraction confidence (0-1)
- `raw_text: Optional[str]` - Original OCR text

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `pytest`
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

