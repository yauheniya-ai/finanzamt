# finanzamt

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://img.shields.io/pypi/v/finanzamt?color=blue&label=PyPI)](https://pypi.org/project/finanzamt/)
[![Tests](https://github.com/yauheniya-ai/finanzamt/actions/workflows/tests.yml/badge.svg)](https://github.com/yauheniya-ai/finanzamt/actions/workflows/tests.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/yauheniya-ai/d09f6edc7b1928aeea1fbde834a6080b/raw/coverage.json)](https://github.com/yauheniya-ai/finanzamt/actions/workflows/tests.yml)
[![GitHub last commit](https://img.shields.io/github/last-commit/yauheniya-ai/finanzamt)](https://github.com/yauheniya-ai/finanzamt/commits/main)
[![Downloads](https://pepy.tech/badge/finanzamt)](https://pepy.tech/project/finanzamt)

A Python library for extracting key information from receipts and preparing essential German tax return statements.

## Features

- **German Tax Alignment**: Category taxonomy and VAT handling aligned with German fiscal practice
- **Local-First**: Everything works locally and completely offline
- **Multi-Agent**: Uses several consequent models for intelligent structured data extraction
- **Rule-based**: Heuristic extraction to enhance the LLM's output
- **Web UI** Full web interface for uploading, extracting, and managing receipts

## Installation

```bash
pip install finanzamt
```

### System Requirements

- Python 3.10+
- Tesseract OCR installed on your system
- Ollama running locally 

#### Tesseract OCR

**Ubuntu / Debian**
```bash
sudo apt-get install tesseract-ocr tesseract-ocr-deu
```

**macOS**
```bash
brew install tesseract tesseract-lang
```

**Windows**

Download the installer from https://github.com/UB-Mannheim/tesseract/wiki and add the installation directory to your `PATH`.

#### Ollama

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull the default model
ollama pull llama3.2
```

## Interactive UI

```bash
pip install finanzamt[ui]
finanzamt --ui
```

<p align="center">
  <img src="https://raw.githubusercontent.com/yauheniya-ai/finanzamt/main/docs/images/Screenshot.png" width="100%" />
  <em>Interactive UI to upload receipts and manage tax statements</em>
</p>

## Quick Start

```python
from finanzamt import FinanceAgent

agent = FinanceAgent()
result = agent.process_receipt("receipt.pdf")

if result.success:
    data = result.data
    print(f"Vendor:  {data.vendor}")
    print(f"Date:    {data.receipt_date}")
    print(f"Total:   {data.total_amount} EUR")
    print(f"VAT:     {data.vat_percentage}% ({data.vat_amount} EUR)")
    print(f"Net:     {data.net_amount} EUR")

    # Serialise to JSON
    with open("extracted.json", "w", encoding="utf-8") as f:
        f.write(data.to_json())
else:
    print(f"Extraction failed: {result.error_message}")
```

## Batch Processing

```python
from pathlib import Path
from finanzamt import FinanceAgent

agent = FinanceAgent()
results = agent.batch_process(Path("receipts/").glob("*.pdf"))

for path, result in results.items():
    if result.success:
        print(f"{path}: {result.data.total_amount} EUR")
    else:
        print(f"{path}: ERROR — {result.error_message}")
```

Or use the bundled example script from the repository:

```bash
python -m examples.batch_process --input-dir receipts/ --output-dir results/ --verbose
```

## Configuration

All settings have sensible defaults and can be overridden in three ways, in priority order:

1. Environment variables prefixed with `FINANZAMT_`
2. A `.env` file in the working directory
3. The built-in defaults

```bash
# .env
FINANZAMT_OLLAMA_BASE_URL=http://localhost:11434
FINANZAMT_MODEL=llama3.2
FINANZAMT_TESSERACT_CMD=tesseract
FINANZAMT_OCR_LANGUAGE=deu+eng
FINANZAMT_OCR_PREPROCESS=true
FINANZAMT_PDF_DPI=300
FINANZAMT_MAX_RETRIES=3
FINANZAMT_REQUEST_TIMEOUT=30
FINANZAMT_TEMPERATURE=0.1
FINANZAMT_TOP_P=0.9
FINANZAMT_NUM_CTX=4096
```

You can also pass a `Config` instance directly:

```python
from finanzamt import FinanceAgent, Config

config = Config(
    model="llama3.2",
    ocr_language="deu+eng",
    pdf_dpi=300,
    max_retries=3,
)
agent = FinanceAgent(config=config)
```

The active configuration can be inspected at runtime:

```python
from finanzamt.config import cfg

print(cfg.model)
print(cfg.get_model_config())   # returns a typed ModelConfig dataclass
```

## API Reference

### FinanceAgent

The main entry point for receipt processing.

```python
class FinanceAgent:
    def __init__(self, config: Config | None = None) -> None: ...

    def process_receipt(
        self, pdf_path: str | Path | bytes
    ) -> ExtractionResult: ...

    def batch_process(
        self, pdf_paths: list[str | Path]
    ) -> dict[str, ExtractionResult]: ...
```

### ExtractionResult

Returned by every `process_receipt` call. Always check `success` before accessing `data`.

```python
@dataclass
class ExtractionResult:
    success: bool
    data: ReceiptData | None
    error_message: str | None
    processing_time: float | None          # seconds

    def to_dict(self) -> dict: ...
```

### ReceiptData

All fields that can be extracted from a receipt.

```python
@dataclass
class ReceiptData:
    vendor: str | None                     # business or store name
    vendor_address: str | None
    receipt_number: str | None
    receipt_date: datetime | None
    total_amount: Decimal | None
    vat_percentage: Decimal | None         # e.g. Decimal("19.0")
    vat_amount: Decimal | None
    net_amount: Decimal | None             # computed: total - vat
    category: ReceiptCategory              # one of RECEIPT_CATEGORIES
    raw_text: str
    items: list[ReceiptItem]

    def to_dict(self) -> dict: ...
    def to_json(self) -> str: ...
```

### ReceiptItem

An individual line item on a receipt.

```python
@dataclass
class ReceiptItem:
    description: str
    total_price: Decimal | None
    quantity: Decimal | None
    unit_price: Decimal | None
    category: ReceiptCategory
    vat_rate: Decimal | None

    def to_dict(self) -> dict: ...
```

### ReceiptCategory

A validated string restricted to the following values:

```
material  equipment  internet  telecommunication  software
education  travel  utilities  insurance  taxes  other
```

```python
from finanzamt import RECEIPT_CATEGORIES   # list[str]
from finanzamt.models import ReceiptCategory

cat = ReceiptCategory("software")          # valid
cat = ReceiptCategory("unknown_value")     # silently normalised to "other"
```

### Exceptions

All exceptions inherit from `FinanceAgentError`:

| Exception | Raised when |
|---|---|
| `OCRProcessingError` | PDF cannot be opened or text extraction fails |
| `LLMExtractionError` | Ollama is unreachable or returns invalid JSON after all retries |
| `InvalidReceiptError` | Extracted data fails business-logic validation |

```python
from finanzamt import FinanceAgentError, OCRProcessingError

try:
    result = agent.process_receipt("scan.pdf")
except OCRProcessingError as e:
    print(e)            # message + cause printed automatically
```

## Supported Receipt Categories

| Category | Typical content |
|---|---|
| `material` | Paper, office consumables, raw materials |
| `equipment` | Hardware, printers, monitors, machines |
| `software` | Licences, SaaS subscriptions, cloud services |
| `internet` | Hosting, domains, broadband, DSL |
| `telecommunication` | Mobile contracts, SIM, telephone |
| `travel` | Flights, rail, hotels, taxis, car rental |
| `education` | Courses, books, certifications, seminars |
| `utilities` | Electricity, gas, water, heating |
| `insurance` | Liability, health, property insurance |
| `taxes` | Tax advisory, filing fees, government charges |
| `other` | Anything that does not match the above |

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-change`)
3. Make your changes
4. Run the test suite: `pytest --cov=src --cov-report=term-missing`
5. Submit a pull request

## License

MIT — see [LICENSE](https://raw.githubusercontent.com/yauheniya-ai/finanzamt/main/LICENSE) for details.
