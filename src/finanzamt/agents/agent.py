"""
finanzamt.agents.agent
~~~~~~~~~~~~~~~
Main entry point for receipt processing.

Pipeline (see agents/pipeline.py for details):
  1. OCR text extraction (Tesseract / Fritz)
  2. Duplicate detection (SHA-256 content hash)
  3. Agent 1 — receipt number, date, category
  4. Agent 2 — counterparty (vendor or client)
  5. Agent 3 — amounts (total, VAT %, VAT amount)
  6. Agent 4 — line items
  7. Python merge of the 4 results → ReceiptData
  8. Validate + auto-save to SQLite

All 4 agents use the same local LLM (configured via FINANZAMT_AGENT_MODEL).
They run sequentially — not in parallel — for local model compatibility.
Debug output is saved to ~/.finanzamt/debug/<receipt_id>/.
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
from .config import Config
from ..storage.sqlite import DEFAULT_DB_PATH, SQLiteRepository
from ..storage.project import resolve_project, layout_from_db_path, ProjectLayout

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

_UNSET = object()  # sentinel: distinguish "not passed" from None


class FinanceAgent:
    """
    Orchestrates OCR + multi-agent extraction and auto-persists every result.

    Args:
        config:      Optional Config instance (reads .env by default).
        project:     Project name — determines ~/.finanzamt/<project>/ layout.
                     Default: "default" (or FINANZAMT_PROJECT env var).
        db_path:     Explicit SQLite path — overrides project layout.
                     Pass None to disable persistence entirely.
        agents_cfg:  Optional AgentsConfig — controls which models are used.
    """

    def __init__(
        self,
        config:     Optional[Config] = None,
        project:    Optional[str] = None,
        db_path:    Union[str, Path, None] = _UNSET,
        agents_cfg: Optional[AgentsConfig] = None,
    ) -> None:
        self.config     = config or Config()
        self.agents_cfg = agents_cfg or AgentsConfig()
        self.ocr        = OCRProcessor(self.config)

        # Resolve project layout
        if db_path is not _UNSET and db_path is not None:
            # Explicit path takes precedence — infer layout from it
            self._layout: Optional[ProjectLayout] = layout_from_db_path(Path(db_path))
            self._db_path: Optional[Path] = Path(db_path)
        elif db_path is None:
            # Explicitly disabled — no persistence
            self._layout = resolve_project(project) if project else None
            self._db_path = None
        else:
            # Normal case — derive everything from project name
            self._layout = resolve_project(project)
            self._db_path = self._layout.db_path

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
                debug_root=self._layout.debug_dir if self._layout else None,
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
        """Copy the original PDF to <project>/pdfs/<id>.pdf."""
        if not src.exists():
            return
        try:
            pdf_dir = (
                self._layout.pdfs_dir
                if self._layout
                else self._db_path.parent / "pdfs"
            )
            pdf_dir.mkdir(parents=True, exist_ok=True)
            dest = pdf_dir / f"{receipt_id}.pdf"
            if not dest.exists():
                shutil.copy2(src, dest)
                logger.info("PDF stored: %s", dest)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not store PDF copy: %s", exc)