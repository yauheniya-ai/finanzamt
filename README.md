# finanzamt

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://img.shields.io/pypi/v/finanzamt?color=blue&label=PyPI)](https://pypi.org/project/finanzamt/)
[![Tests](https://github.com/yauheniya-ai/finanzamt/actions/workflows/tests.yml/badge.svg)](https://github.com/yauheniya-ai/finanzamt/actions/workflows/tests.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/yauheniya-ai/d09f6edc7b1928aeea1fbde834a6080b/raw/coverage.json)](https://github.com/yauheniya-ai/finanzamt/actions/workflows/tests.yml)
[![GitHub last commit](https://img.shields.io/github/last-commit/yauheniya-ai/finanzamt)](https://github.com/yauheniya-ai/finanzamt/commits/main)
[![Downloads](https://pepy.tech/badge/finanzamt)](https://pepy.tech/project/finanzamt)

A Python library for extracting structured data from receipts and invoices and preparing essential German VAT statements.

## Features

- **German Tax Alignment** — Category taxonomy and VAT handling aligned with German fiscal practice (Vorsteuer / Umsatzsteuer, UStVA line numbers)
- **Local-First** — Everything runs locally and completely offline; no data leaves your machine
- **4-Agent Pipeline** — Sequential specialised agents for metadata, counterparty, amounts, and line items; short focused prompts for reliable local model performance
- **Purchases and Sales** — Handles both incoming invoices (Eingangsrechnungen) and outgoing invoices (Ausgangsrechnungen)
- **Counterparty Deduplication** — Vendors and clients are stored once and reused across receipts
- **Web UI** — Full browser interface for uploading, reviewing, editing, and managing receipts

## Tech Stack

- <img src="https://api.iconify.design/devicon:python.svg" width="16" height="16"> Python — package language
- <img src="https://api.iconify.design/devicon:fastapi.svg" width="16" height="16"> FastAPI — backend for the web UI
- <img src="https://api.iconify.design/devicon:react.svg" width="16" height="16"> React — interactive frontend
- <img src="https://api.iconify.design/devicon:google.svg" width="16" height="16"> Tesseract — OCR for scanned PDFs
- <img src="https://api.iconify.design/devicon:ollama.svg" width="16" height="16"> Ollama — local LLM for structured extraction

## Installation

```bash
pip install finanzamt
```

### System Requirements

- Python 3.10+
- Tesseract OCR installed on your system
- Ollama running locally with a supported model pulled

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

# Pull a model — qwen2.5 7B is the recommended default
ollama pull qwen2.5:7b-instruct-q4_K_M
```

Other models that work well: `qwen3:8b`, `llama3.2`, `llama3.1`.

## Quick Start

### Interactive UI

```bash
pip install finanzamt[ui]
finanzamt --ui
```

<p align="center">
  <img src="https://raw.githubusercontent.com/yauheniya-ai/finanzamt/main/docs/images/Screenshot.png" width="100%" />
  <em>Interactive UI to upload receipts and manage tax statements</em>
</p>

### Python API

#### Process a single receipt (expense)

```python
from finanzamt import FinanceAgent

agent = FinanceAgent()
result = agent.process_receipt("receipt.pdf")

if result.success:
    data = result.data
    print(f"Counterparty: {data.vendor}")
    print(f"Date:         {data.receipt_date}")
    print(f"Total:        {data.total_amount} EUR")
    print(f"VAT:          {data.vat_percentage}% ({data.vat_amount} EUR)")
    print(f"Net:          {data.net_amount} EUR")
    print(f"Category:     {data.category}")
    print(f"Items:        {len(data.items)}")

    # Serialise to JSON
    with open("extracted.json", "w", encoding="utf-8") as f:
        f.write(data.to_json())
else:
    print(f"Extraction failed: {result.error_message}")
```

#### Sale invoices (outgoing)

```python
result = agent.process_receipt("invoice_to_client.pdf", receipt_type="sale")
```

#### Batch processing

```python
from pathlib import Path
from finanzamt import FinanceAgent

agent = FinanceAgent()
results = agent.batch_process(list(Path("receipts/").glob("*.pdf")))

for path, result in results.items():
    if result.success:
        print(f"{path}: {result.data.total_amount} EUR")
    else:
        print(f"{path}: ERROR — {result.error_message}")
```

## Configuration

Settings are read in priority order from: environment variables → `.env` file → built-in defaults.

```bash
# .env

# OCR and general settings
FINANZAMT_OLLAMA_BASE_URL=http://localhost:11434
FINANZAMT_TESSERACT_CMD=tesseract
FINANZAMT_OCR_LANGUAGE=deu+eng
FINANZAMT_OCR_PREPROCESS=true
FINANZAMT_PDF_DPI=300

# Extraction agents — all 4 agents use this model
FINANZAMT_AGENT_MODEL=qwen2.5:7b-instruct-q4_K_M
FINANZAMT_AGENT_TIMEOUT=60
FINANZAMT_AGENT_NUM_CTX=4096
FINANZAMT_AGENT_MAX_RETRIES=2
```

You can also pass config objects directly:

```python
from finanzamt import FinanceAgent
from finanzamt.agents.config import Config, AgentsConfig

agent = FinanceAgent(
    config=Config(ocr_language="deu+eng", pdf_dpi=300),
    agents_cfg=AgentsConfig(agent_model="qwen3:8b"),
)
```

## API Reference

### FinanceAgent

```python
class FinanceAgent:
    def __init__(
        self,
        config:     Config | None = None,
        db_path:    str | Path | None = "~/.finanzamt/finanzamt.db",
        agents_cfg: AgentsConfig | None = None,
    ) -> None: ...

    def process_receipt(
        self,
        pdf_path:     str | Path | bytes,
        receipt_type: str = "purchase",   # "purchase" or "sale"
    ) -> ExtractionResult: ...

    def batch_process(
        self,
        pdf_paths:    list[str | Path],
        receipt_type: str = "purchase",
    ) -> dict[str, ExtractionResult]: ...
```

### ExtractionResult

Always check `success` before accessing `data`.

```python
@dataclass
class ExtractionResult:
    success:         bool
    data:            ReceiptData | None
    error_message:   str | None
    duplicate:       bool                  # True if already in the database
    existing_id:     str | None            # ID of the original if duplicate
    processing_time: float | None          # seconds

    def to_dict(self) -> dict: ...
```

### ReceiptData

```python
@dataclass
class ReceiptData:
    id:               str                  # SHA-256 of OCR text — stable dedup key
    receipt_type:     ReceiptType          # "purchase" or "sale"
    counterparty:     Counterparty | None  # vendor (purchase) or client (sale)
    receipt_number:   str | None
    receipt_date:     datetime | None
    total_amount:     Decimal | None
    vat_percentage:   Decimal | None       # e.g. Decimal("19.0")
    vat_amount:       Decimal | None
    net_amount:       Decimal | None       # computed: total - vat
    category:         ReceiptCategory
    items:            list[ReceiptItem]
    vat_splits:       list[dict]           # for mixed-rate invoices

    vendor: str | None                     # alias for counterparty.name

    def to_dict(self) -> dict: ...
    def to_json(self) -> str: ...
```

### Counterparty

```python
@dataclass
class Counterparty:
    id:          str           # UUID assigned by the database
    name:        str | None
    vat_id:      str | None    # EU format, e.g. DE123456789
    tax_number:  str | None    # German Steuernummer, e.g. 123/456/78901
    address:     Address
    verified:    bool          # manually confirmed in the UI
```

### ReceiptItem

```python
@dataclass
class ReceiptItem:
    position:    int | None
    description: str
    quantity:    Decimal | None
    unit_price:  Decimal | None
    total_price: Decimal | None
    vat_rate:    Decimal | None
    vat_amount:  Decimal | None
    category:    ReceiptCategory

    def to_dict(self) -> dict: ...
```

### ReceiptCategory

A validated string subclass. Invalid values are silently normalised to `"other"`.

```python
from finanzamt.agents.prompts import RECEIPT_CATEGORIES   # list[str]
from finanzamt.models import ReceiptCategory

cat = ReceiptCategory("software")       # valid
cat = ReceiptCategory("unknown_value")  # normalised to "other"
cat = ReceiptCategory.other()           # explicit fallback
```

### Exceptions

All exceptions inherit from `FinanceAgentError`.

| Exception | Raised when |
|---|---|
| `OCRProcessingError` | PDF cannot be opened or text extraction fails |
| `LLMExtractionError` | Ollama is unreachable or returns invalid JSON after all retries |
| `InvalidReceiptError` | Extracted data fails business-logic validation |

```python
from finanzamt.exceptions import FinanceAgentError, OCRProcessingError

try:
    result = agent.process_receipt("scan.pdf")
except OCRProcessingError as e:
    print(e)
```

## Extraction Pipeline

Each receipt goes through four sequential LLM calls, each with a short focused prompt:

| Agent | Extracts |
|---|---|
| Agent 1 | Receipt number, date, category |
| Agent 2 | Counterparty name, VAT ID, Steuernummer, address |
| Agent 3 | Total amount, VAT percentage, VAT amount |
| Agent 4 | Line items (description, VAT rate, VAT amount, price) |

Results are merged in Python — no additional LLM validation step. Debug output for every agent (prompt, raw response, parsed JSON) is saved to `~/.finanzamt/debug/<receipt_id>/`.

## Supported Categories

| Category | Typical content | Direction |
|---|---|---|
| `material` | Paper, office consumables, raw materials | purchase |
| `equipment` | Hardware, printers, monitors, machines | purchase |
| `software` | Licences, SaaS subscriptions, cloud services | purchase |
| `internet` | Hosting, domains, broadband | purchase |
| `telecommunication` | Mobile contracts, SIM, telephone | purchase |
| `travel` | Flights, rail, hotels, taxis, car rental | purchase |
| `education` | Courses, books, certifications, seminars | purchase |
| `utilities` | Electricity, gas, water, heating | purchase |
| `insurance` | Liability, health, property insurance | purchase |
| `taxes` | Tax advisory, filing fees, government charges | purchase |
| `services` | Freelance / service work billed to a client | sale |
| `consulting` | Advisory or consulting project billed to a client | sale |
| `products` | Physical goods sold to a client | sale |
| `licensing` | Software or IP rights licensed to a client | sale |
| `other` | Anything that does not match the above | either |

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-change`)
3. Make your changes
4. Run the test suite: `pytest --cov=src --cov-report=term-missing`
5. Submit a pull request

## License

MIT — see [LICENSE](https://raw.githubusercontent.com/yauheniya-ai/finanzamt/main/LICENSE) for details.