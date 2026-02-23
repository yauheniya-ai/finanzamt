"""
finanzamt.agent
~~~~~~~~~~~~~~~
Main entry point for receipt processing.

Pipeline:
  1. OCR text extraction
  2. Duplicate detection (SHA-256 content hash)
  3. LLM structured extraction → rule-based fallback
  4. Model construction + validation
  5. Auto-save to SQLite (always; no explicit save required)
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional, Union

import requests

from .config import Config
from .exceptions import InvalidReceiptError, LLMExtractionError, OCRProcessingError
from .models import (
    Address, Counterparty, ExtractionResult,
    ReceiptCategory, ReceiptData, ReceiptItem, ReceiptType,
    _content_hash,
)
from .ocr_processor import OCRProcessor
from .prompts import build_extraction_prompt
from .storage.sqlite import DEFAULT_DB_PATH, SQLiteRepository
from .utils import DataExtractor, clean_json_response, parse_date, parse_decimal

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class FinanceAgent:
    """
    Orchestrates OCR + LLM extraction and auto-persists every result.

    Args:
        config:  Optional Config instance (reads .env by default).
        db_path: SQLite database path.
                 Default: ``~/.finanzamt/finanzamt.db``.
                 Pass ``None`` to disable persistence entirely.
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        db_path: Union[str, Path, None] = DEFAULT_DB_PATH,
    ) -> None:
        self.config = config or Config()
        self.ocr_processor = OCRProcessor(self.config)
        self.data_extractor = DataExtractor()
        self._db_path: Optional[Path] = Path(db_path) if db_path else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_receipt(
        self,
        pdf_path: Union[str, Path, bytes],
        receipt_type: str = "purchase",
    ) -> ExtractionResult:
        """
        Process a receipt PDF and return structured data.

        The result is automatically saved to the local database unless
        the agent was constructed with ``db_path=None``.

        Duplicate detection is content-based: if a receipt with the same
        OCR text has already been processed, ``ExtractionResult.duplicate``
        is ``True`` and ``ExtractionResult.existing_id`` contains the
        original receipt's ID.  The result still contains the full
        ``ReceiptData`` so callers can inspect the previously-extracted data.

        Args:
            pdf_path:     Filesystem path or raw PDF bytes.
            receipt_type: ``"purchase"`` (default) or ``"sale"``.
        """
        start = time.monotonic()

        try:
            # 1 — OCR -------------------------------------------------------
            raw_text = self.ocr_processor.extract_text_from_pdf(pdf_path)
            if not raw_text.strip():
                return ExtractionResult(
                    success=False,
                    error_message="No text could be extracted from the receipt.",
                    processing_time=time.monotonic() - start,
                )

            # 2 — Duplicate check -------------------------------------------
            content_id = _content_hash(raw_text)
            if self._db_path:
                with SQLiteRepository(self._db_path) as repo:
                    if repo.exists(content_id):
                        existing = repo.get(content_id)
                        logger.info("Duplicate receipt detected: %s", content_id)
                        return ExtractionResult(
                            success=True,
                            data=existing,
                            duplicate=True,
                            existing_id=content_id,
                            processing_time=time.monotonic() - start,
                        )

            # 3 — LLM extraction --------------------------------------------
            llm_result: Optional[dict] = None
            try:
                llm_result = self._extract_with_llm(raw_text)
            except LLMExtractionError as exc:
                logger.warning("LLM failed (%s); using rule-based fallback.", exc)

            if not llm_result or not llm_result.get("items"):
                llm_result = self._extract_with_rules(raw_text, receipt_type)

            # 4 — Build model -----------------------------------------------
            receipt_data = self._build_receipt_data(
                llm_result, raw_text, receipt_type
            )

            if not receipt_data.validate():
                raise InvalidReceiptError(
                    f"Receipt data failed validation — "
                    f"total={receipt_data.total_amount}, date={receipt_data.receipt_date}"
                )

            # 5 — Auto-save + PDF copy ------------------------------------
            if self._db_path:
                with SQLiteRepository(self._db_path) as repo:
                    repo.save(receipt_data)
                # Copy original PDF alongside the DB for later display
                if isinstance(pdf_path, (str, Path)):
                    self._store_pdf(Path(pdf_path), receipt_data.id)

            return ExtractionResult(
                success=True,
                data=receipt_data,
                processing_time=time.monotonic() - start,
            )

        except (OCRProcessingError, LLMExtractionError, InvalidReceiptError) as exc:
            logger.error("%s: %s", type(exc).__name__, exc)
            return ExtractionResult(
                success=False,
                error_message=str(exc),
                processing_time=time.monotonic() - start,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error processing receipt.")
            return ExtractionResult(
                success=False,
                error_message=f"Unexpected error: {exc}",
                processing_time=time.monotonic() - start,
            )

    def batch_process(
        self,
        pdf_paths: list[Union[str, Path]],
        receipt_type: str = "purchase",
    ) -> dict[str, ExtractionResult]:
        """Process multiple receipts sequentially."""
        return {
            str(p): self.process_receipt(p, receipt_type=receipt_type)
            for p in pdf_paths
        }


    def _store_pdf(self, src: Path, receipt_id: str) -> None:
        """Copy the original PDF to ~/.finanzamt/pdfs/<hash>.pdf."""
        if not src.exists():
            return
        try:
            pdf_dir = self._db_path.parent / "pdfs"
            pdf_dir.mkdir(parents=True, exist_ok=True)
            dest = pdf_dir / f"{receipt_id}.pdf"
            if not dest.exists():
                shutil.copy2(src, dest)
                logger.info("PDF stored: %s", dest)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not store PDF copy: %s", exc)

    # ------------------------------------------------------------------
    # LLM extraction
    # ------------------------------------------------------------------

    def _extract_with_llm(self, text: str) -> dict:
        model_cfg = self.config.get_model_config()
        prompt = build_extraction_prompt(text)

        for attempt in range(1, model_cfg.max_retries + 1):
            try:
                response = requests.post(
                    f"{model_cfg.base_url}/api/generate",
                    json={
                        "model":  model_cfg.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": model_cfg.temperature,
                            "top_p":       model_cfg.top_p,
                            "num_ctx":     model_cfg.num_ctx,
                        },
                    },
                    timeout=model_cfg.timeout,
                )
                if response.status_code != 200:
                    logger.warning(
                        "Attempt %d/%d — Ollama HTTP %d",
                        attempt, model_cfg.max_retries, response.status_code,
                    )
                    continue
                raw = response.json().get("response", "")
                return json.loads(clean_json_response(raw))

            except json.JSONDecodeError as exc:
                logger.warning("Attempt %d/%d — invalid JSON: %s", attempt, model_cfg.max_retries, exc)
            except requests.exceptions.RequestException as exc:
                logger.warning("Attempt %d/%d — request failed: %s", attempt, model_cfg.max_retries, exc)
                time.sleep(1)

        raise LLMExtractionError(
            f"Ollama extraction failed after {model_cfg.max_retries} attempts."
        )

    # ------------------------------------------------------------------
    # Rule-based fallback
    # ------------------------------------------------------------------

    def _extract_with_rules(self, text: str, receipt_type: str = "purchase") -> dict:
        dt = self.data_extractor.extract_date(text)
        amounts = self.data_extractor.extract_amounts(text)
        vat_info = self.data_extractor.extract_vat_info(text)
        return {
            "receipt_type":           receipt_type,
            "counterparty_name":      self.data_extractor.extract_company_name(text),
            "counterparty_address":   {},
            "counterparty_tax_number": None,
            "counterparty_vat_id":    None,
            "receipt_number":         None,
            "receipt_date":           dt.strftime("%Y-%m-%d") if dt else None,
            "total_amount":           float(amounts["total"]) if amounts.get("total") else None,
            "vat_percentage":         float(vat_info["vat_percentage"]) if vat_info.get("vat_percentage") else None,
            "vat_amount":             float(vat_info["vat_amount"]) if vat_info.get("vat_amount") else None,
            "category":               "other",
            "items":                  self.data_extractor.extract_items(text),
        }

    # ------------------------------------------------------------------
    # Model construction
    # ------------------------------------------------------------------

    def _build_receipt_data(
        self, data: dict, raw_text: str, default_type: str = "purchase"
    ) -> ReceiptData:
        # --- Counterparty ---
        addr_raw = data.get("counterparty_address") or {}
        address = Address(
            street=        addr_raw.get("street"),
            street_number= addr_raw.get("street_number"),
            postcode=      addr_raw.get("postcode"),
            city=          addr_raw.get("city"),
            country=       addr_raw.get("country"),
        )
        cp_name = data.get("counterparty_name")
        counterparty: Optional[Counterparty] = None
        if cp_name or any(vars(address).values()):
            counterparty = Counterparty(
                name=       cp_name,
                address=    address,
                tax_number= data.get("counterparty_tax_number"),
                vat_id=     data.get("counterparty_vat_id"),
            )

        # --- Line items ---
        items: list[ReceiptItem] = []
        for item_data in data.get("items") or []:
            try:
                items.append(ReceiptItem(
                    description= item_data.get("description", ""),
                    quantity=    parse_decimal(item_data.get("quantity")),
                    unit_price=  parse_decimal(item_data.get("unit_price")),
                    total_price= parse_decimal(item_data.get("total_price")),
                    category=    ReceiptCategory(item_data.get("category", "other")),
                    vat_rate=    parse_decimal(item_data.get("vat_rate")),
                ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skipping malformed line item: %s", exc)

        # --- Receipt type ---
        rtype = str(data.get("receipt_type") or default_type)

        raw_date = data.get("receipt_date")

        return ReceiptData(
            raw_text=       raw_text,
            receipt_type=   ReceiptType(rtype),
            counterparty=   counterparty,
            receipt_number= data.get("receipt_number"),
            receipt_date=   parse_date(raw_date) if raw_date else None,
            total_amount=   parse_decimal(data.get("total_amount")),
            vat_percentage= parse_decimal(data.get("vat_percentage")),
            vat_amount=     parse_decimal(data.get("vat_amount")),
            category=       ReceiptCategory(data.get("category", "other")),
            items=          items,
        )