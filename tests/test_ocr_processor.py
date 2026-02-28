"""
tests/test_ocr_processor.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for finanzamt.ocr_processor — OCRProcessor with PyMuPDF and
pytesseract mocked so tests run without any system dependencies.
"""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, call, patch

import pytest

from finanzamt.agents.config import Config
from finanzamt.exceptions import OCRProcessingError
from finanzamt.ocr_processor import OCRProcessor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_page(direct_text: str = "", ocr_text: str = "") -> MagicMock:
    """Build a fake fitz.Page."""
    page = MagicMock()
    page.get_text.return_value = direct_text

    # get_pixmap → fake pixmap → tobytes → PNG bytes
    pix = MagicMock()
    pix.tobytes.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64   # minimal fake PNG
    page.get_pixmap.return_value = pix

    return page


def _make_mock_pdf(pages: list[MagicMock]) -> MagicMock:
    """Build a fake fitz.Document."""
    doc = MagicMock()
    doc.page_count = len(pages)
    doc.__getitem__ = lambda self, i: pages[i]
    return doc


# ---------------------------------------------------------------------------
# Tesseract configuration
# ---------------------------------------------------------------------------

class TestConfigureTesseract:
    def test_default_cmd_does_not_override_pytesseract(self):
        """When tesseract_cmd is the default, pytesseract.tesseract_cmd must not be set."""
        with patch("finanzamt.ocr_processor.pytesseract") as mock_tess:
            # spec=[] means MagicMock starts with NO attributes — any assignment
            # will be detectable via hasattr, while unassigned ones return False.
            mock_tess.pytesseract = MagicMock(spec=[])
            OCRProcessor(Config(tesseract_cmd="tesseract"))
            assert not hasattr(mock_tess.pytesseract, "tesseract_cmd")

    def test_custom_cmd_sets_pytesseract_path(self):
        custom_path = "/usr/local/bin/tesseract"
        with patch("finanzamt.ocr_processor.pytesseract") as mock_tess:
            mock_tess.pytesseract = MagicMock()
            OCRProcessor(Config(tesseract_cmd=custom_path))
            assert mock_tess.pytesseract.tesseract_cmd == custom_path


# ---------------------------------------------------------------------------
# extract_text_from_pdf — direct text layer
# ---------------------------------------------------------------------------

class TestExtractDirectText:
    def test_returns_direct_text_when_available(self):
        page = _make_mock_page(direct_text="Invoice text here")
        doc = _make_mock_pdf([page])

        with patch("finanzamt.ocr_processor.fitz.open", return_value=doc), \
             patch("finanzamt.ocr_processor.pytesseract"):
            proc = OCRProcessor()
            result = proc.extract_text_from_pdf("receipt.pdf")

        assert "Invoice text here" in result

    def test_direct_text_skips_ocr(self):
        page = _make_mock_page(direct_text="Direct text")
        doc = _make_mock_pdf([page])

        with patch("finanzamt.ocr_processor.fitz.open", return_value=doc), \
             patch("finanzamt.ocr_processor.pytesseract") as mock_tess:
            proc = OCRProcessor()
            proc.extract_text_from_pdf("receipt.pdf")
            mock_tess.image_to_string.assert_not_called()

    def test_multiple_pages_concatenated(self):
        pages = [
            _make_mock_page(direct_text="Page one"),
            _make_mock_page(direct_text="Page two"),
        ]
        doc = _make_mock_pdf(pages)

        with patch("finanzamt.ocr_processor.fitz.open", return_value=doc), \
             patch("finanzamt.ocr_processor.pytesseract"):
            result = OCRProcessor().extract_text_from_pdf("receipt.pdf")

        assert "Page one" in result
        assert "Page two" in result

    def test_pdf_closed_after_success(self):
        page = _make_mock_page(direct_text="text")
        doc = _make_mock_pdf([page])

        with patch("finanzamt.ocr_processor.fitz.open", return_value=doc), \
             patch("finanzamt.ocr_processor.pytesseract"):
            OCRProcessor().extract_text_from_pdf("receipt.pdf")

        doc.close.assert_called_once()


# ---------------------------------------------------------------------------
# extract_text_from_pdf — OCR path
# ---------------------------------------------------------------------------

class TestExtractOcrPath:
    def test_ocr_called_when_no_direct_text(self):
        page = _make_mock_page(direct_text="")
        doc = _make_mock_pdf([page])

        with patch("finanzamt.ocr_processor.fitz.open", return_value=doc), \
             patch("finanzamt.ocr_processor.Image") as mock_img, \
             patch("finanzamt.ocr_processor.pytesseract") as mock_tess:
            mock_tess.image_to_string.return_value = "OCR extracted text"
            mock_img.open.return_value = MagicMock()
            result = OCRProcessor().extract_text_from_pdf("scanned.pdf")

        mock_tess.image_to_string.assert_called_once()
        assert "OCR extracted text" in result

    def test_dpi_respected_in_matrix(self):
        """Regression: was hardcoded fitz.Matrix(2,2) = 144 DPI, ignoring config."""
        page = _make_mock_page(direct_text="")
        doc = _make_mock_pdf([page])
        config = Config(pdf_dpi=300)
        expected_scale = 300 / 72.0

        with patch("finanzamt.ocr_processor.fitz.open", return_value=doc), \
             patch("finanzamt.ocr_processor.fitz.Matrix") as mock_matrix, \
             patch("finanzamt.ocr_processor.Image") as mock_img, \
             patch("finanzamt.ocr_processor.pytesseract") as mock_tess:
            mock_tess.image_to_string.return_value = ""
            mock_img.open.return_value = MagicMock()
            OCRProcessor(config).extract_text_from_pdf("scanned.pdf")

        mock_matrix.assert_called_with(expected_scale, expected_scale)

    def test_ocr_language_passed_to_tesseract(self):
        page = _make_mock_page(direct_text="")
        doc = _make_mock_pdf([page])
        config = Config(ocr_language="deu")

        with patch("finanzamt.ocr_processor.fitz.open", return_value=doc), \
             patch("finanzamt.ocr_processor.Image") as mock_img, \
             patch("finanzamt.ocr_processor.pytesseract") as mock_tess:
            mock_tess.image_to_string.return_value = ""
            mock_img.open.return_value = MagicMock()
            OCRProcessor(config).extract_text_from_pdf("scanned.pdf")

        call_args = mock_tess.image_to_string.call_args
        config_str = call_args[1].get("config") or call_args[0][1]
        assert "deu" in config_str

    def test_pdf_closed_after_ocr_error(self):
        """Regression: file handle leaked when an exception occurred mid-loop."""
        page = _make_mock_page(direct_text="")
        doc = _make_mock_pdf([page])

        with patch("finanzamt.ocr_processor.fitz.open", return_value=doc), \
             patch("finanzamt.ocr_processor.Image") as mock_img, \
             patch("finanzamt.ocr_processor.pytesseract") as mock_tess:
            mock_tess.image_to_string.side_effect = RuntimeError("tess crash")
            mock_img.open.return_value = MagicMock()
            result = OCRProcessor().extract_text_from_pdf("scanned.pdf")

        # OCR error is swallowed (returns "") — but the file must be closed
        doc.close.assert_called_once()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_raises_ocr_error_on_bad_pdf(self):
        with patch("finanzamt.ocr_processor.fitz.open", side_effect=RuntimeError("corrupt")):
            with pytest.raises(OCRProcessingError):
                OCRProcessor().extract_text_from_pdf("bad.pdf")

    def test_accepts_bytes_input(self):
        page = _make_mock_page(direct_text="bytes text")
        doc = _make_mock_pdf([page])

        with patch("finanzamt.ocr_processor.fitz.open", return_value=doc) as mock_open, \
             patch("finanzamt.ocr_processor.pytesseract"):
            OCRProcessor().extract_text_from_pdf(b"%PDF-1.4 bytes content")
            # Must be called with stream= keyword, not as a path
            call_kwargs = mock_open.call_args[1]
            assert "stream" in call_kwargs

    def test_returns_stripped_text(self):
        page = _make_mock_page(direct_text="  lots of whitespace  \n\n")
        doc = _make_mock_pdf([page])

        with patch("finanzamt.ocr_processor.fitz.open", return_value=doc), \
             patch("finanzamt.ocr_processor.pytesseract"):
            result = OCRProcessor().extract_text_from_pdf("receipt.pdf")

        assert result == result.strip()


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------

class TestPreprocessImage:
    def test_preprocess_returns_image(self):
        import numpy as np
        from PIL import Image as PILImage
        img = PILImage.fromarray((255 * (1 - __import__("numpy").random.rand(100, 100))).astype("uint8"), mode="L")

        with patch("finanzamt.ocr_processor.cv2") as mock_cv2:
            mock_cv2.fastNlMeansDenoising.return_value = img
            mock_cv2.convertScaleAbs.return_value     = img
            mock_cv2.threshold.return_value           = (None, img)
            result = OCRProcessor._preprocess_image(img)

        assert result is not None

    def test_preprocess_returns_original_on_failure(self):
        from PIL import Image as PILImage
        img = PILImage.new("RGB", (10, 10))

        with patch("finanzamt.ocr_processor.cv2") as mock_cv2:
            mock_cv2.fastNlMeansDenoising.side_effect = RuntimeError("cv2 error")
            result = OCRProcessor._preprocess_image(img)

        # Should return the original image, not raise
        assert result is img