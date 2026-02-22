"""
finanzamt.ocr_processor
~~~~~~~~~~~~~~~~~~~~~~~~
OCR extraction from PDF receipts using PyMuPDF + Tesseract.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Optional, Union

import cv2
import fitz  # PyMuPDF
import numpy as np
import pytesseract
from PIL import Image

from .config import Config
from .exceptions import OCRProcessingError

logger = logging.getLogger(__name__)


class OCRProcessor:
    """Extract plain text from PDF receipts via OCR."""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or Config()
        self._configure_tesseract()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _configure_tesseract(self) -> None:
        """Point pytesseract at the correct binary when a custom path is set."""
        if self.config.tesseract_cmd != "tesseract":
            pytesseract.pytesseract.tesseract_cmd = self.config.tesseract_cmd

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
                    pages_text.append(direct_text)
                else:
                    # Scanned / image page — run OCR
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
        Rasterise one PDF page and run Tesseract OCR on it.

        The render resolution is taken from ``config.pdf_dpi`` (default 300).
        PyMuPDF's default canvas is 72 DPI, so the scale factor is
        ``pdf_dpi / 72``.
        """
        try:
            scale = self.config.pdf_dpi / 72.0
            matrix = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image = Image.open(io.BytesIO(pix.tobytes("png")))

            if self.config.ocr_preprocess:
                image = self._preprocess_image(image)

            # --psm 6: assume a single uniform block of text (good for receipts)
            # --oem 3: use both legacy and LSTM engines
            tess_config = f"--oem 3 --psm 6 -l {self.config.ocr_language}"
            return pytesseract.image_to_string(image, config=tess_config)

        except Exception as exc:
            logger.warning("OCR failed on page, returning empty string: %s", exc)
            return ""

    @staticmethod
    def _preprocess_image(image: Image.Image) -> Image.Image:
        """
        Apply standard pre-processing steps that improve OCR accuracy on
        typical German receipt scans:

        1. Convert to greyscale
        2. Denoise (fast non-local means)
        3. Boost contrast slightly
        4. Binarise with Otsu's threshold
        """
        try:
            img = np.array(image.convert("L"))          # greyscale, always safe

            img = cv2.fastNlMeansDenoising(             # denoise
                img, h=10, templateWindowSize=7, searchWindowSize=21
            )
            img = cv2.convertScaleAbs(img, alpha=1.2, beta=10)  # contrast
            _, img = cv2.threshold(                     # binarise
                img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )
            return Image.fromarray(img)

        except Exception as exc:
            logger.warning("Image pre-processing failed, using original: %s", exc)
            return image