"""
finanzamt.agent
~~~~~~~~~~~~~~~
Main entry point for receipt processing.

Pipeline (see agents/pipeline.py for details):
  1. OCR text extraction
  2. Duplicate detection (SHA-256 content hash)
  3. Rule-based extractor  → hints
  4. Agent 1 (text LLM)   → json1
  5. Agent 2 (vision LLM) → json2
  6. Agent 3 (Validator)  → json3  (merged, sanity-checked)
  7. Build ReceiptData from best available result
  8. Validate + auto-save to SQLite
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Optional, Union

from .pipeline import run_pipeline
from .config import AgentsConfig
from ..exceptions import InvalidReceiptError, OCRProcessingError
from ..models import ExtractionResult, ReceiptData, _content_hash
from ..ocr_processor import OCRProcessor
from ..agents.config import Config
from ..storage.sqlite import DEFAULT_DB_PATH, SQLiteRepository

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class FinanceAgent:
    """
    Orchestrates OCR + multi-agent extraction and auto-persists every result.

    Args:
        config:      Optional Config instance (reads .env by default).
        db_path:     SQLite database path.
                     Default: ~/.finanzamt/finanzamt.db
                     Pass None to disable persistence.
        agents_cfg:  Optional AgentsConfig — controls which models are used
                     for each agent. Reads from env/dotenv by default.
    """

    def __init__(
        self,
        config:     Optional[Config] = None,
        db_path:    Union[str, Path, None] = DEFAULT_DB_PATH,
        agents_cfg: Optional[AgentsConfig] = None,
    ) -> None:
        self.config      = config or Config()
        self.agents_cfg  = agents_cfg or AgentsConfig()
        self.ocr         = OCRProcessor(self.config)
        self._db_path: Optional[Path] = Path(db_path) if db_path else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_receipt(
        self,
        pdf_path:     Union[str, Path, bytes],
        receipt_type: str = "purchase",
    ) -> ExtractionResult:
        """
        Process a receipt or invoice PDF through the full pipeline.

        Args:
            pdf_path:     Filesystem path or raw PDF bytes.
            receipt_type: "purchase" (default) or "sale".

        Returns ExtractionResult — always populated, success flag indicates
        whether the result passed validation and was saved.
        """
        start = time.monotonic()

        try:
            # 1 — OCR -------------------------------------------------------
            raw_text = self.ocr.extract_text_from_pdf(pdf_path)
            if not raw_text.strip():
                return ExtractionResult(
                    success=False,
                    error_message="No text could be extracted from the PDF.",
                    processing_time=time.monotonic() - start,
                )

            # 2 — Duplicate check -------------------------------------------
            content_id = _content_hash(raw_text)
            if self._db_path:
                with SQLiteRepository(self._db_path) as repo:
                    if repo.exists(content_id):
                        existing = repo.get(content_id)
                        logger.info("Duplicate detected: %s", content_id)
                        return ExtractionResult(
                            success=True,
                            data=existing,
                            duplicate=True,
                            existing_id=content_id,
                            processing_time=time.monotonic() - start,
                        )

            # 3-7 — Multi-agent extraction ----------------------------------
            pdf_file_path: Optional[Path] = (
                Path(pdf_path) if isinstance(pdf_path, (str, Path)) else None
            )
            receipt_data: ReceiptData = run_pipeline(
                raw_text=raw_text,
                pdf_path=pdf_file_path,
                receipt_type=receipt_type,
                cfg=self.agents_cfg,
                receipt_id=content_id,
            )

            # 8 — Validate --------------------------------------------------
            if not receipt_data.validate():
                raise InvalidReceiptError(
                    f"Receipt failed validation — "
                    f"total={receipt_data.total_amount}, date={receipt_data.receipt_date}"
                )

            # 9 — Save + PDF copy -------------------------------------------
            if self._db_path:
                with SQLiteRepository(self._db_path) as repo:
                    repo.save(receipt_data)
                if pdf_file_path:
                    self._store_pdf(pdf_file_path, receipt_data.id)

            return ExtractionResult(
                success=True,
                data=receipt_data,
                processing_time=time.monotonic() - start,
            )

        except (OCRProcessingError, InvalidReceiptError) as exc:
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
        pdf_paths:    list[Union[str, Path]],
        receipt_type: str = "purchase",
    ) -> dict[str, ExtractionResult]:
        """Process multiple receipts sequentially."""
        return {
            str(p): self.process_receipt(p, receipt_type=receipt_type)
            for p in pdf_paths
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _store_pdf(self, src: Path, receipt_id: str) -> None:
        """Copy the original PDF to <db_dir>/pdfs/<id>.pdf."""
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