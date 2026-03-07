# finanzamt

<div align="center">

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://img.shields.io/pypi/v/finanzamt?color=blue&label=PyPI)](https://pypi.org/project/finanzamt/)
[![Tests](https://github.com/yauheniya-ai/finanzamt/actions/workflows/tests.yml/badge.svg)](https://github.com/yauheniya-ai/finanzamt/actions/workflows/tests.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/yauheniya-ai/d09f6edc7b1928aeea1fbde834a6080b/raw/coverage.json)](https://github.com/yauheniya-ai/finanzamt/actions/workflows/tests.yml)
[![GitHub last commit](https://img.shields.io/github/last-commit/yauheniya-ai/finanzamt)](https://github.com/yauheniya-ai/finanzamt/commits/main)
[![Downloads](https://pepy.tech/badge/finanzamt)](https://pepy.tech/project/finanzamt)


[English](https://raw.githubusercontent.com/yauheniya-ai/finanzamt/main/README.md) • Deutsch

</div>

Eine Python-Bibliothek zur strukturierten Extraktion von Daten aus Belegen und Rechnungen sowie zur Erstellung wesentlicher deutscher Umsatzsteuervoranmeldungen.

## Funktionen

- **Deutsche Steuerkonformität** — Kategoriensystem und Umsatzsteuerbehandlung ausgerichtet auf die deutsche Buchführungspraxis (Vorsteuer / Umsatzsteuer, UStVA-Kennzahlen)
- **Lokal & Offline** — Alles läuft lokal und vollständig offline; keine Daten verlassen Ihren Rechner
- **4-Agenten-Pipeline** — Vier sequenzielle, spezialisierte Agenten für Metadaten, Geschäftspartner, Beträge und Positionen; kurze, fokussierte Prompts für zuverlässige Leistung mit lokalen Modellen
- **Eingangs- und Ausgangsrechnungen** — Verarbeitet sowohl Eingangsrechnungen als auch Ausgangsrechnungen
- **Deduplizierung von Geschäftspartnern** — Lieferanten und Kunden werden einmalig gespeichert und belegübergreifend wiederverwendet
- **Web-Oberfläche** — Vollständige Browseroberfläche zum Hochladen, Prüfen, Bearbeiten und Verwalten von Belegen

## Technologie-Stack

- <img src="https://api.iconify.design/devicon:python.svg" width="16" height="16"> Python — Paketsprache
- <img src="https://api.iconify.design/devicon:fastapi.svg" width="16" height="16"> FastAPI — Backend der Web-Oberfläche
- <img src="https://api.iconify.design/devicon:react.svg" width="16" height="16"> React — Interaktives Frontend
- <img src="https://api.iconify.design/simple-icons:paddlepaddle.svg" width="16" height="16"> PaddleOCR — OCR für gescannte PDFs
- <img src="https://api.iconify.design/devicon:google.svg" width="16" height="16"> Tesseract — OCR für gescannte PDFs und Bilder als Fallback bei PaddleOCR-Fehlern oder Timeouts
- <img src="https://api.iconify.design/devicon:ollama.svg" width="16" height="16"> Ollama — Lokale LLMs zur strukturierten Extraktion von Beleginformationen
- <img src="https://api.iconify.design/hugeicons:qwen.svg" width="16" height="16"> Qwen — Laptop-kompatible LLMs; qwen2.5:7b-instruct-q4_K_M ist derzeit das empfohlene Standardmodell für textbasierte Extraktion
- <img src="https://api.iconify.design/devicon:sqlite.svg" width="16" height="16"> SQLite — Lokale Datenbank für Originalbelege und extrahierte Daten

## Installation

```bash
pip install finanzamt
```

### Systemvoraussetzungen

- Python 3.10+
- Ollama läuft lokal mit einem unterstützten, heruntergeladenen Modell
- Tesseract OCR (optionaler Fallback bei PaddleOCR-Timeout)

#### Ollama

```bash
# Ollama installieren
curl -fsSL https://ollama.ai/install.sh | sh

# Modell laden — qwen2.5 7B ist der empfohlene Standard
ollama pull qwen2.5:7b-instruct-q4_K_M
```

Weitere gut funktionierende Modelle: `qwen3:8b`, `llama3.2`, `llama3.1`.

#### Tesseract OCR (optionaler Fallback für PaddleOCR)

**Ubuntu / Debian**
```bash
sudo apt-get install tesseract-ocr tesseract-ocr-deu
```

**macOS**
```bash
brew install tesseract tesseract-lang
```

**Windows**

Installer herunterladen von https://github.com/UB-Mannheim/tesseract/wiki und zum `PATH` hinzufügen.

## Schnellstart

### Interaktive Oberfläche

```bash
pip install "finanzamt[ui]"
finanzamt --ui
```

<p align="center">
  <img src="https://raw.githubusercontent.com/yauheniya-ai/finanzamt/main/docs/images/Demo.webp" width="100%" />
  <em>Interaktive Oberfläche zum Hochladen von Belegen und Verwalten von Steuererklärungen</em>
</p>

### Python-API

#### Einzelnen Beleg verarbeiten (Ausgabe)

```python
from finanzamt import FinanceAgent

agent = FinanceAgent()
result = agent.process_receipt("beleg.pdf")

if result.success:
    data = result.data
    print(f"Geschäftspartner: {data.vendor}")
    print(f"Datum:            {data.receipt_date}")
    print(f"Gesamtbetrag:     {data.total_amount} EUR")
    print(f"MwSt.:            {data.vat_percentage}% ({data.vat_amount} EUR)")
    print(f"Nettobetrag:      {data.net_amount} EUR")
    print(f"Kategorie:        {data.category}")
    print(f"Positionen:       {len(data.items)}")

    # Als JSON serialisieren
    with open("extrahiert.json", "w", encoding="utf-8") as f:
        f.write(data.to_json())
else:
    print(f"Extraktion fehlgeschlagen: {result.error_message}")
```

#### Ausgangsrechnungen

```python
result = agent.process_receipt("rechnung_an_kunden.pdf", receipt_type="sale")
```

#### Stapelverarbeitung

```python
from pathlib import Path
from finanzamt import FinanceAgent

agent = FinanceAgent()
results = agent.batch_process(list(Path("belege/").glob("*.pdf")))

for path, result in results.items():
    if result.success:
        print(f"{path}: {result.data.total_amount} EUR")
    else:
        print(f"{path}: FEHLER — {result.error_message}")
```

## Konfiguration

Einstellungen werden in folgender Prioritätsreihenfolge eingelesen: Umgebungsvariablen → `.env`-Datei → eingebaute Standardwerte.

```bash
# .env

# OCR und allgemeine Einstellungen
FINANZAMT_OLLAMA_BASE_URL=http://localhost:11434
FINANZAMT_OCR_LANGUAGE=german
FINANZAMT_OCR_TIMEOUT=60
FINANZAMT_TESSERACT_CMD=tesseract
FINANZAMT_OCR_PREPROCESS=true
FINANZAMT_PDF_DPI=150

# Extraktionsagenten — alle 4 Agenten verwenden dieses Modell
FINANZAMT_AGENT_MODEL=qwen2.5:7b-instruct-q4_K_M
FINANZAMT_AGENT_TIMEOUT=60
FINANZAMT_AGENT_NUM_CTX=4096
FINANZAMT_AGENT_MAX_RETRIES=2
```

Konfigurationsobjekte können auch direkt übergeben werden:

```python
from finanzamt import FinanceAgent
from finanzamt.agents.config import Config, AgentsConfig

agent = FinanceAgent(
    config=Config(ocr_language="deu+eng", pdf_dpi=150),
    agents_cfg=AgentsConfig(agent_model="qwen3:8b"),
)
```

## API-Referenz

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
        receipt_type: str = "purchase",   # "purchase" oder "sale"
    ) -> ExtractionResult: ...

    def batch_process(
        self,
        pdf_paths:    list[str | Path],
        receipt_type: str = "purchase",
    ) -> dict[str, ExtractionResult]: ...
```

### ExtractionResult

`success` sollte immer vor dem Zugriff auf `data` geprüft werden.

```python
@dataclass
class ExtractionResult:
    success:         bool
    data:            ReceiptData | None
    error_message:   str | None
    duplicate:       bool                  # True, wenn bereits in der Datenbank
    existing_id:     str | None            # ID des Originals bei Duplikat
    processing_time: float | None          # Sekunden

    def to_dict(self) -> dict: ...
```

### ReceiptData

```python
@dataclass
class ReceiptData:
    id:               str                  # SHA-256 des OCR-Textes — stabiler Deduplizierungsschlüssel
    receipt_type:     ReceiptType          # "purchase" oder "sale"
    counterparty:     Counterparty | None  # Lieferant (Eingang) oder Kunde (Ausgang)
    receipt_number:   str | None
    receipt_date:     datetime | None
    total_amount:     Decimal | None
    vat_percentage:   Decimal | None       # z. B. Decimal("19.0")
    vat_amount:       Decimal | None
    net_amount:       Decimal | None       # berechnet: Gesamt minus MwSt.
    category:         ReceiptCategory
    items:            list[ReceiptItem]
    vat_splits:       list[dict]           # für Rechnungen mit gemischten Steuersätzen

    vendor: str | None                     # Alias für counterparty.name

    def to_dict(self) -> dict: ...
    def to_json(self) -> str: ...
```

### Counterparty

```python
@dataclass
class Counterparty:
    id:          str           # Von der Datenbank vergebene UUID
    name:        str | None
    vat_id:      str | None    # EU-Format, z. B. DE123456789
    tax_number:  str | None    # Deutsche Steuernummer, z. B. 123/456/78901
    address:     Address
    verified:    bool          # Manuell in der Oberfläche bestätigt
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

Eine validierte String-Unterklasse. Ungültige Werte werden stillschweigend auf `"other"` normalisiert.

```python
from finanzamt.agents.prompts import RECEIPT_CATEGORIES   # list[str]
from finanzamt.models import ReceiptCategory

cat = ReceiptCategory("software")       # gültig
cat = ReceiptCategory("unbekannter_wert")  # wird auf "other" normalisiert
cat = ReceiptCategory.other()           # expliziter Fallback
```

### Ausnahmen

Alle Ausnahmen erben von `FinanceAgentError`.

| Ausnahme | Wird ausgelöst bei |
|---|---|
| `OCRProcessingError` | PDF kann nicht geöffnet werden oder Textextraktion schlägt fehl |
| `LLMExtractionError` | Ollama nicht erreichbar oder gibt nach allen Versuchen kein gültiges JSON zurück |
| `InvalidReceiptError` | Extrahierte Daten bestehen die fachliche Validierung nicht |

```python
from finanzamt.exceptions import FinanceAgentError, OCRProcessingError

try:
    result = agent.process_receipt("scan.pdf")
except OCRProcessingError as e:
    print(e)
```

## Extraktions-Pipeline

Jeder Beleg durchläuft vier sequenzielle LLM-Aufrufe, jeweils mit einem kurzen, fokussierten Prompt:

| Agent | Extrahiert |
|---|---|
| Agent 1 | Belegnummer, Datum, Kategorie |
| Agent 2 | Name des Geschäftspartners, USt-IdNr., Steuernummer, Adresse |
| Agent 3 | Gesamtbetrag, Umsatzsteuersatz, Umsatzsteuerbetrag |
| Agent 4 | Positionen (Beschreibung, MwSt.-Satz, MwSt.-Betrag, Preis) |

Die Ergebnisse werden in Python zusammengeführt — kein zusätzlicher LLM-Validierungsschritt. Die Debug-Ausgabe jedes Agenten (Prompt, Rohantwort, geparste JSON) wird unter `~/.finanzamt/debug/<beleg_id>/` gespeichert.

## Unterstützte Kategorien

| Kategorie | Typischer Inhalt | Richtung |
|---|---|---|
| `material` | Papier, Bürobedarf, Rohstoffe | Eingang |
| `equipment` | Hardware, Drucker, Monitore, Maschinen | Eingang |
| `software` | Lizenzen, SaaS-Abonnements, Cloud-Dienste | Eingang |
| `internet` | Hosting, Domains, Breitband | Eingang |
| `telecommunication` | Mobilfunkverträge, SIM, Telefon | Eingang |
| `travel` | Flüge, Bahn, Hotels, Taxis, Mietwagen | Eingang |
| `education` | Kurse, Bücher, Zertifizierungen, Seminare | Eingang |
| `utilities` | Strom, Gas, Wasser, Heizung | Eingang |
| `insurance` | Haftpflicht, Kranken-, Sachversicherung | Eingang |
| `taxes` | Steuerberatung, Gebühren, Abgaben | Eingang |
| `services` | Freiberufliche Leistungen / Dienstleistungen an Kunden | Ausgang |
| `consulting` | Beratungsprojekte für Kunden | Ausgang |
| `products` | Physische Waren an Kunden | Ausgang |
| `licensing` | Software- oder IP-Rechte für Kunden | Ausgang |
| `other` | Alles, was keiner der obigen Kategorien entspricht | beides |

## Aufgabenliste
- [x] Beleganalyse
- [x] Steuerberechnungsmodul
- [ ] ELSTER-Feldzuordnung
- [ ] XML-Generator
- [ ] XSD-Validierung

## Mitwirken

1. Repository forken
2. Feature-Branch erstellen (`git checkout -b feature/meine-änderung`)
3. Änderungen vornehmen
4. Testsuite ausführen: `pytest --cov=src --cov-report=term-missing`
5. Pull Request einreichen

## Lizenz

MIT — siehe [LICENSE](https://raw.githubusercontent.com/yauheniya-ai/finanzamt/main/LICENSE) für Details.

## Haftungsausschluss

`finanzamt` ist ein unabhängiges Open-Source-Projekt und steht in keiner Verbindung zu deutschen Steuerbehörden oder ELSTER, wird von diesen weder unterstützt noch vertreten.