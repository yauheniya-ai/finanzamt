"""
finamt.ocr_processor
~~~~~~~~~~~~~~~~~~~~~~~~
OCR extraction from PDF receipts using PyMuPDF + PaddleOCR with
Tesseract as a fallback when PaddleOCR times out or fails.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeout
from finamt import progress as _progress
from pathlib import Path
from typing import Optional, Union

import fitz  # PyMuPDF
from PIL import Image

from .agents.config import Config
from .exceptions import OCRProcessingError

# Must be set before any paddle import
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

logger = logging.getLogger(__name__)


def _ts() -> str:
    return time.strftime("[%H:%M:%S]")

# ---------------------------------------------------------------------------
# PaddleOCR singleton — model loads once, reused for all receipts
# ---------------------------------------------------------------------------
_paddle_ocr_instance = None
_paddle_ocr_error: Optional[str] = None


def _get_paddle_ocr():
    global _paddle_ocr_instance, _paddle_ocr_error

    if _paddle_ocr_error:
        return None, _paddle_ocr_error
    if _paddle_ocr_instance is not None:
        return _paddle_ocr_instance, None

    try:
        from paddleocr import PaddleOCR
        # lang='german' covers full Latin alphabet; handles German/English mix
        _paddle_ocr_instance = PaddleOCR(use_textline_orientation=True, lang="german")
        return _paddle_ocr_instance, None
    except ImportError as e:
        _paddle_ocr_error = (
            f"PaddleOCR import failed — {e}. "
            "Install with: pip install paddleocr paddlepaddle"
        )
        return None, _paddle_ocr_error
    except Exception as e:
        _paddle_ocr_error = f"PaddleOCR init failed: {type(e).__name__}: {e}"
        return None, _paddle_ocr_error


def _extract_texts_from_paddle_result(result) -> list[str]:
    """Pull rec_texts out of a PaddleOCR predict() result."""
    lines: list[str] = []
    for page_result in result:
        rec_texts = (
            page_result.get("rec_texts")
            if hasattr(page_result, "get")
            else getattr(page_result, "rec_texts", None)
        )
        if rec_texts:
            lines.extend([t for t in rec_texts if t and t.strip()])
    return lines


class OCRProcessor:
    """Extract plain text from PDF receipts via OCR."""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or Config()
        self._configure_tesseract()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _configure_tesseract(self) -> None:
        """Point pytesseract at the correct binary when a custom path is configured."""
        if self.config.tesseract_cmd != "tesseract":
            try:
                import pytesseract
                pytesseract.pytesseract.tesseract_cmd = self.config.tesseract_cmd
            except ImportError:
                pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_text_from_pdf(self, pdf_path: Union[str, Path, bytes]) -> str:
        """
        Extract text from every page of a PDF.

        Tries direct text extraction first (fast, lossless); falls back to
        OCR for scanned / image-only pages.

        Args:
            pdf_path: Filesystem path, ``pathlib.Path``, or raw PDF bytes.

        Returns:
            Concatenated text from all pages, stripped of leading/trailing whitespace.

        Raises:
            OCRProcessingError: On any unrecoverable PDF or I/O error.
        """
        try:
            if isinstance(pdf_path, bytes):
                pdf_doc = fitz.open(stream=pdf_path, filetype="pdf")
            else:
                pdf_doc = fitz.open(str(pdf_path))
        except Exception as exc:
            raise OCRProcessingError(
                f"Could not open PDF: {pdf_path}", cause=exc
            ) from exc

        pages_text: list[str] = []
        try:
            for page_num in range(pdf_doc.page_count):
                page = pdf_doc[page_num]
                direct_text = page.get_text().strip()
                if direct_text:
                    # Embedded text layer — no OCR needed
                    _progress.emit(f"  {_ts()} → PDF text layer (page {page_num + 1})")
                    pages_text.append(direct_text)
                else:
                    # Scanned / image page — run OCR
                    _progress.emit(f"  {_ts()} → OCR page {page_num + 1}/{pdf_doc.page_count} ...")
                    ocr_text = self._ocr_page(page)
                    pages_text.append(ocr_text)
        finally:
            pdf_doc.close()   # always release the file handle

        return "\n".join(pages_text).strip()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ocr_page(self, page: fitz.Page) -> str:
        """
        Rasterise one PDF page, write a temp PNG, and call OCR.

        PaddleOCR is attempted first inside a ``ThreadPoolExecutor`` with a
        ``config.ocr_timeout`` second deadline (default 60 s).  When it Times
        out or raises, Tesseract is used as a fallback so the process never
        hangs or gets killed by the OS.
        """
        tmp_path: str | None = None
        try:
            scale = self.config.pdf_dpi / 72.0
            matrix = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=matrix, alpha=False)

            # Write to a temp file — PaddleOCR reads from disk efficiently
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
                pix.save(tmp_path)

            return self._paddle_with_fallback(tmp_path)

        except Exception as exc:
            logger.warning("OCR page rendering failed, returning empty string: %s", exc)
            return ""
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _paddle_with_fallback(self, image_path: str) -> str:
        """
        Try PaddleOCR with a timeout; transparently fall back to Tesseract
        on timeout, OOM, or any other failure.
        """
        ocr, error = _get_paddle_ocr()
        if not error:
            try:
                _progress.emit(f"    {_ts()} → PaddleOCR ...")
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(ocr.predict, image_path)
                    result = future.result(timeout=self.config.ocr_timeout)
                lines = _extract_texts_from_paddle_result(result)
                if lines:
                    logger.debug("PaddleOCR extracted %d lines", len(lines))
                    return "\n".join(lines)
                logger.debug("PaddleOCR returned no text, trying Tesseract")
            except _FuturesTimeout:
                _progress.emit(f"    {_ts()} → PaddleOCR timed out ({self.config.ocr_timeout}s) — Tesseract fallback")
                logger.warning(
                    "PaddleOCR timed out after %ds — falling back to Tesseract",
                    self.config.ocr_timeout,
                )
            except Exception as exc:
                _progress.emit(f"    {_ts()} → PaddleOCR failed ({type(exc).__name__}) — Tesseract fallback")
                logger.warning("PaddleOCR error: %s: %s", type(exc).__name__, exc)
        else:
            _progress.emit(f"    {_ts()} → PaddleOCR unavailable — Tesseract fallback")
            logger.warning("PaddleOCR unavailable (%s) — using Tesseract", error)

        return self._tesseract_ocr(image_path)

    def _tesseract_ocr(self, image_path: str) -> str:
        """Run Tesseract on the given image file. Returns '' if unavailable."""
        _progress.emit(f"      {_ts()} → Tesseract ...")
        try:
            import pytesseract
        except ImportError:
            logger.warning(
                "pytesseract not installed — Tesseract fallback unavailable. "
                "Install with: pip install pytesseract"
            )
            return ""

        try:
            img = Image.open(image_path)
            text = pytesseract.image_to_string(img, lang="deu+eng")
            logger.debug("Tesseract fallback produced %d chars", len(text))
            return text
        except Exception as exc:
            logger.warning("Tesseract fallback failed: %s", exc)
            return ""