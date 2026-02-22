"""
finanzamt.agent
~~~~~~~~~~~~~~~
The main entry point for receipt processing.

``FinanceAgent`` orchestrates the full pipeline:
  1. OCR text extraction (``OCRProcessor``)
  2. LLM-based structured extraction (Ollama)
  3. Rule-based fallback (``DataExtractor``)
  4. Model construction + validation (``ReceiptData``)
"""

from __future__ import annotations

import json
import logging
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional, Union

import requests

from .config import Config
from .exceptions import InvalidReceiptError, LLMExtractionError, OCRProcessingError
from .models import ExtractionResult, ReceiptCategory, ReceiptData, ReceiptItem
from .ocr_processor import OCRProcessor
from .prompts import build_extraction_prompt
from .utils import DataExtractor, clean_json_response, parse_date, parse_decimal

# Libraries must never call basicConfig — attach a NullHandler so that log
# records are silently discarded unless the *application* configures logging.
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class FinanceAgent:
    """
    Agentic AI system for processing German financial receipts.

    Combines OCR text extraction with an Ollama LLM for structured data
    extraction, falling back to heuristic rules when the LLM is unavailable
    or returns malformed output.

    Args:
        config: Optional ``Config`` instance.  If omitted, a default ``Config``
                is created (reads from ``.env`` and environment variables).
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or Config()
        self.ocr_processor = OCRProcessor(self.config)
        self.data_extractor = DataExtractor()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_receipt(
        self,
        pdf_path: Union[str, Path, bytes],
    ) -> ExtractionResult:
        """
        Process a receipt PDF and return structured financial data.

        Args:
            pdf_path: Filesystem path, ``pathlib.Path``, or raw PDF bytes.

        Returns:
            ``ExtractionResult`` — always succeeds structurally; check
            ``result.success`` and ``result.error_message`` for failures.
        """
        start = time.monotonic()

        try:
            # 1 — OCR -------------------------------------------------------
            logger.info("Extracting text from receipt…")
            raw_text = self.ocr_processor.extract_text_from_pdf(pdf_path)

            if not raw_text.strip():
                return ExtractionResult(
                    success=False,
                    error_message="No text could be extracted from the receipt.",
                    processing_time=time.monotonic() - start,
                )

            # 2 — LLM extraction --------------------------------------------
            logger.info("Running LLM extraction…")
            llm_result: Optional[dict] = None
            try:
                llm_result = self._extract_with_llm(raw_text)
            except LLMExtractionError as exc:
                logger.warning("LLM extraction failed (%s); falling back to rules.", exc)

            # 3 — Rule-based fallback ---------------------------------------
            if not llm_result or not llm_result.get("items"):
                logger.info("Using rule-based fallback extraction.")
                llm_result = self._extract_with_rules(raw_text)

            # 4 — Build model -----------------------------------------------
            receipt_data = self._build_receipt_data(llm_result, raw_text)

            if not receipt_data.validate():
                raise InvalidReceiptError(
                    "Extracted receipt data failed validation — "
                    f"total={receipt_data.total_amount}, date={receipt_data.receipt_date}"
                )

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
    ) -> dict[str, ExtractionResult]:
        """
        Process multiple receipts sequentially.

        Args:
            pdf_paths: Iterable of PDF file paths.

        Returns:
            ``{str(path): ExtractionResult}`` for every input path.
        """
        results: dict[str, ExtractionResult] = {}
        for pdf_path in pdf_paths:
            logger.info("Processing %s …", pdf_path)
            results[str(pdf_path)] = self.process_receipt(pdf_path)
        return results

    # ------------------------------------------------------------------
    # LLM extraction
    # ------------------------------------------------------------------

    def _extract_with_llm(self, text: str) -> dict:
        """
        Call Ollama and parse the JSON response.

        Retries up to ``config.max_retries`` times with a short backoff.

        Raises:
            LLMExtractionError: When all attempts are exhausted.
        """
        model_cfg = self.config.get_model_config()   # returns ModelConfig dataclass
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
                        "Attempt %d/%d — Ollama returned HTTP %d.",
                        attempt, model_cfg.max_retries, response.status_code,
                    )
                    continue

                raw_response = response.json().get("response", "")
                cleaned = clean_json_response(raw_response)
                return json.loads(cleaned)

            except json.JSONDecodeError as exc:
                logger.warning("Attempt %d/%d — invalid JSON: %s", attempt, model_cfg.max_retries, exc)
            except requests.exceptions.RequestException as exc:
                logger.warning("Attempt %d/%d — request failed: %s", attempt, model_cfg.max_retries, exc)
                time.sleep(1)  # brief backoff before retry

        raise LLMExtractionError(
            f"Ollama extraction failed after {model_cfg.max_retries} attempts."
        )

    # ------------------------------------------------------------------
    # Rule-based fallback
    # ------------------------------------------------------------------

    def _extract_with_rules(self, text: str) -> dict:
        """
        Heuristic extraction for when the LLM is unavailable.

        Returns a dict with the same keys as the LLM prompt JSON so that
        ``_build_receipt_data`` can handle both paths identically.
        """
        date = self.data_extractor.extract_date(text)
        amounts = self.data_extractor.extract_amounts(text)
        vat_info = self.data_extractor.extract_vat_info(text)

        return {
            "vendor":         self.data_extractor.extract_company_name(text),
            "vendor_address": None,
            "receipt_number": None,
            "receipt_date":   date.strftime("%Y-%m-%d") if date else None,
            "total_amount":   float(amounts["total"]) if amounts.get("total") else None,
            "vat_percentage": float(vat_info["vat_percentage"]) if vat_info.get("vat_percentage") else None,
            "vat_amount":     float(vat_info["vat_amount"]) if vat_info.get("vat_amount") else None,
            "category":       "other",
            "items":          self.data_extractor.extract_items(text),
        }

    # ------------------------------------------------------------------
    # Model construction
    # ------------------------------------------------------------------

    def _build_receipt_data(self, data: dict, raw_text: str) -> ReceiptData:
        """
        Map a raw extraction dict (from LLM or rules) to a ``ReceiptData``
        instance.  Field names match those defined in the extraction prompt.
        """
        items: list[ReceiptItem] = []
        for item_data in data.get("items") or []:
            try:
                items.append(
                    ReceiptItem(
                        description=item_data.get("description", ""),
                        quantity=   parse_decimal(item_data.get("quantity")),
                        unit_price= parse_decimal(item_data.get("unit_price")),
                        total_price=parse_decimal(item_data.get("total_price")),
                        category=   ReceiptCategory(item_data.get("category", "other")),
                        vat_rate=   parse_decimal(item_data.get("vat_rate")),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skipping malformed line item: %s", exc)

        raw_date = data.get("receipt_date")
        parsed_date = parse_date(raw_date) if raw_date else None

        return ReceiptData(
            vendor=          data.get("vendor"),
            vendor_address=  data.get("vendor_address"),
            receipt_number=  data.get("receipt_number"),
            receipt_date=    parsed_date,
            total_amount=    parse_decimal(data.get("total_amount")),
            vat_percentage=  parse_decimal(data.get("vat_percentage")),
            vat_amount=      parse_decimal(data.get("vat_amount")),
            category=        ReceiptCategory(data.get("category", "other")),
            raw_text=        raw_text,
            items=           items,
        )