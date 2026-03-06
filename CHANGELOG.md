# Changelog

## Version 0.4.5 (2026-03-05)

Switch OCR engine to PaddleOCR with Tesseract fallback
- **PaddleOCR** is the primary OCR engine; model is installed automatically via pip (`paddleocr`, `paddlepaddle`) and loaded once as a singleton
- **Tesseract fallback** — PaddleOCR runs inside a `ThreadPoolExecutor` with a configurable timeout (`FINANZAMT_OCR_TIMEOUT`, default 60 s); on timeout or any failure the process falls back to Tesseract, preventing OOM kills
- **German language model** — PaddleOCR uses `lang='german'`; Tesseract fallback uses `deu+eng`
- **`FINANZAMT_OCR_TIMEOUT`** — new config field (int, seconds, default 60) controlling how long to wait for PaddleOCR before switching to Tesseract
- **`FINANZAMT_TESSERACT_CMD`** — re-introduced so the Tesseract binary path can be customised when not on `PATH`
- **Temp-file approach** — page pixmaps are saved to a temp PNG and passed by path to PaddleOCR; file is deleted in `finally`
- **Event Streaming** – add event streaming to the terminal and the frontend

## Version 0.4.4 (2026-03-01)

Address schema refactor: unified street address and added state field
- **Schema consolidation** — merged `street` and `street_number` into a single `street_and_number` field for cleaner UI and extraction
- **State/province support** — added `state` field to address model for better international address handling (e.g. US states, German Bundesländer)
- **Database migration** — schema maintains backward compatibility; existing `street`/`street_number` data is automatically migrated to `street_and_number` on first run
- **Agent 2 prompt update** — extraction now expects `street_and_number` instead of separate fields; improved extraction rules documentation
- **Frontend address editor** — simplified from 2 address fields to 1; street number is now combined with street name
- **Localization updates** — locale keys updated: `field_street_and_number`, `field_state` added (EN: "Street", "State/Province"; DE: "Straße", "Bundesland")
- **Address display** — `formatAddress()` now correctly handles combined street and optional state in address formatting

## Version 0.4.3 (2026-03-01)

Packaging fix:
- Ensure the static folder (HTML, JS, CSS assets) is included in the PyPI package by adding MANIFEST.in and setting include-package-data = true in pyproject.toml. Now static assets are present after installation from PyPI.

## Version 0.4.2 (2026-03-01)

Improvements of the PreviewPanel and Dashboard
- Add support for previewing images (PNG, SVG, WebP, JPEG, JPG)
- Add go back button for the fullscreen preview
- Add to the dashboard a list of tax return statements that are coming soon

## Version 0.4.1 (2026-03-01)

Multi-project storage and full German UI translation
- **Multi-project storage** — receipts, PDFs, and debug output are now grouped under `~/.finanzamt/<project>/`; the default project lives at `~/.finanzamt/default/` (breaking change from the flat layout)
- **Project selector** — create, switch, and delete named projects directly from the header without restarting the server
- **German translation** — complete DE/EN localisation for Sidebar, PreviewPanel, Dashboard, and the project selector; language toggle in the header
- **Dashboard period label** — the subtitle now shows the currently selected time period (e.g. Q1 2025, März 2025) instead of a receipt count
- **Category and type translation** — receipt type (Ausgabe/Einnahme) and all category labels are now translated in the preview panel and category charts
- **DB creation guard** — the database file is created only on first upload, not on the initial page load; prevents stray files in the wrong directory

## Version 0.4.0 (2026-03-01)

Agentic workflow improvement
- **Four-agent pipeline** — metadata, counterparty, amounts, and line items are each extracted by a dedicated agent with a short focused prompt, improving reliability on local models
- **Debug output** — full prompt, raw model response, and parsed JSON are saved per agent to `~/.finanzamt/debug/<receipt_id>/` for inspection
- **Rule-based extraction removed** — all structured data now comes from the LLM pipeline

UI and database improvements
- **Period filter** — sidebar lets you filter receipts by year, quarter, or month; Dashboard reflects the active selection
- **Sidebar translation** — DE/EN locale support added to the sidebar
- **Counterparty verification** — mark a counterparty as verified in the preview panel and reuse it across receipts via the verified-counterparty picker
- **Address toggle** — full address details in the preview panel are collapsed by default and expanded on demand
- **VAT splitting** — receipts with multiple VAT rates can have each rate entered separately; splits are stored and displayed in the panel
- **Line item editing** — add, edit, and delete line items directly in the preview panel with per-item VAT rate and amount fields

## Version 0.3.2 (2026-02-25)

UI improvements for receipt management and database selection:
- Database selector: users can now choose a database, and all previously processed receipts are loaded automatically.
- Receipt browsing: receipts are grouped and displayed by year, quarter, and month for easier navigation.
- Revenue vs expense categorization: all receipts are classified and summarized per category, with totals shown for each.
- Editable records: editing receipts in the UI updates the corresponding records directly in the database.

## Version 0.3.1 (2026-02-24)

Added internationalisation infrastructure and German/English language toggle to the web UI header.
- DE/EN toggle: header now has a language switcher — amber track for German, red for English, black thumb; purely React-state-driven (no native input conflict)
- react-i18next: i18n infrastructure wired via `src/i18n.ts` with `de.json` and `en.json` locale files; components use `t("key")` and `i18n.changeLanguage()`
- Header localised: subtitle translates on toggle; install command stays hardcoded in English as `pip install finanzamt` — intentionally not translated
- Copy button: classic two-squares icon next to the install command copies it to clipboard; swaps to a green checkmark for 2s on success

## Version 0.3.0 (2026-02-24)

Full UI for receipt management:
	- Web interface for uploading and extracting receipts
	- Real-time extraction status and results display
	- Drag-and-drop PDF upload with batch support
	- Integrated static assets for responsive layout and branding
	- API endpoints for programmatic access and automation


## Version 0.2.0 (2026-02-23)

Persistent storage layer with content-addressed receipts, counterparty deduplication, and purchase/sale VAT split
- 4-table schema: `receipts`, `receipt_items`, `receipt_content`, `counterparties` — each concern in its own table
- Content-addressed IDs: receipt ID is a SHA-256 hash of OCR text; identical content = automatic duplicate detection with user notification
- Purchase vs sale split: `ReceiptType` distinguishes Eingangsrechnung (Vorsteuer you reclaim) from Ausgangsrechnung (Umsatzsteuer you remit); UStVA liability = output − input
- Counterparty model: replaces flat `vendor` string with structured `Counterparty` (parsed address, Steuernummer, USt-IdNr); deduplication by VAT ID then name
- Auto-save: every successful extraction persists to `~/.finanzamt/finanzamt.db` automatically; JSON output is now opt-in via `--output-dir`
- PDF archive: original PDF copied to `~/.finanzamt/pdfs/<hash>.pdf` for later display alongside extracted data
- Test suite updated: storage, UStVA, agent, CLI, and model tests rewritten for new API; all 250+ tests passing


## Version 0.1.5 (2026-02-22)

Add CLI and tests
- CLI refactor: Introduced a class-based CLI with commands for version reporting, single receipt processing, and batch processing. CLI logic is now testable in-process.
- CLI tests: Added in-process and subprocess tests for CLI functionality, improving coverage and reliability.

## Version 0.1.4 (2026-02-22)

Refactor config and models, unify prompt categories, fix OCR and utils, and update examples for consistent schema alignment
- Config refactor: Replaced scattered `os.getenv` calls with `pydantic-settings.BaseSettings`; all runtime settings are validated, typed, and overridable by `FINANZAMT_` env vars.  
- Unified model config: Promoted key model params (`temperature`, `top_p`, `num_ctx`) to validated fields; `get_model_config()` now returns a frozen `ModelConfig` dataclass.  
- Prompt separation: Moved extraction templates and category definitions (`RECEIPT_CATEGORIES`, `build_extraction_prompt`) to a new `prompts.py` for cleaner separation of config and prompt logic.  
- Schema alignment: Replaced outdated `ItemCategory` enum with `ReceiptCategory` validated against prompt categories; updated field names (`vendor`, `total_amount`, etc.) for full LLM schema alignment.  
- Validation and serialization: Added computed `net_amount`, VAT validation, and rounded `processing_time` in output.  
- Agent improvements: Fixed crashes from attribute misaccess; unified rule-based and LLM extraction paths; added robust retry and timing logic with structured logging.  
- OCR processor fixes: DPI scaling now respects config, closes PDFs safely on errors, and uses lowercase config fields consistently.  
- Utilities overhaul: Corrected date parsing and German amount handling; improved regex safety and amount extraction heuristics.  
- Exception clarity: Custom exception base now auto-appends cause info, producing cleaner tracebacks.  
- Examples updated: Scripts now use new field names, category logic, output options, and proper exit codes for batch and single receipt processing.  

## Version 0.1.3 (2026-02-21)

Major refactor: package renamed and structure updated
- Renamed package from 'ai-finance-agent' to 'finanzamt'.
- Updated project structure to src/finanzamt for imports and packaging.

## Version 0.1.2 (2025-07-10)

Minor improvements and bug fixes
- Improved extraction logic.
- Fixed minor bugs.

## Version 0.1.1 (2025-07-10)

Initial package upload
- Uploaded ai-finance-agent to PyPI.
- Added basic documentation.

## Version 0.1.0 (2025-07-10)

First release: basic receipt processing
- Implemented receipt parsing and extraction.
- Provided initial agent interface.