# Changelog

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