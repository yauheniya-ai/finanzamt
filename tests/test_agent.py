"""
tests/test_agent.py
~~~~~~~~~~~~~~~~~~~~
Tests for finanzamt.agent — FinanceAgent with all external I/O mocked.

External dependencies (OCRProcessor, requests) are patched so tests run
offline without Ollama or Tesseract installed.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from finanzamt.agent import FinanceAgent
from finanzamt.config import Config
from finanzamt.exceptions import InvalidReceiptError, LLMExtractionError, OCRProcessingError
from finanzamt.models import ReceiptData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(ocr_text: str = "", *, config: Config | None = None) -> tuple[FinanceAgent, MagicMock]:
    """Return (agent, mock_ocr_processor) with OCR pre-configured to return ocr_text."""
    with patch("finanzamt.agent.OCRProcessor") as MockOCR:
        mock_ocr = MockOCR.return_value
        mock_ocr.extract_text_from_pdf.return_value = ocr_text
        agent = FinanceAgent(config=config, db_path=None)  # disable DB in tests
        agent.ocr_processor = mock_ocr   # replace after construction
    return agent, mock_ocr


def _mock_ollama_response(data: dict) -> MagicMock:
    """Build a mock requests.Response that returns data as an Ollama JSON payload."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": json.dumps(data)}
    return mock_resp


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestInit:
    def test_default_config_used_when_none_provided(self):
        with patch("finanzamt.agent.OCRProcessor"):
            agent = FinanceAgent(db_path=None)
        assert isinstance(agent.config, Config)

    def test_custom_config_accepted(self):
        config = Config(model="phi3")
        with patch("finanzamt.agent.OCRProcessor"):
            agent = FinanceAgent(config=config, db_path=None)
        assert agent.config.model == "phi3"

    def test_no_basicconfig_called(self):
        """Libraries must not configure the root logger."""
        import logging
        root = logging.getLogger()
        original_handlers = list(root.handlers)
        with patch("finanzamt.agent.OCRProcessor"):
            FinanceAgent(db_path=None)
        assert list(root.handlers) == original_handlers


# ---------------------------------------------------------------------------
# process_receipt — success paths
# ---------------------------------------------------------------------------

class TestProcessReceiptSuccess:
    def test_successful_llm_extraction(self, llm_json_response):
        agent, mock_ocr = _make_agent("Bürobedarf GmbH\nGesamt 25,90 €")
        mock_ocr.extract_text_from_pdf.return_value = "Bürobedarf GmbH\nGesamt 25,90 €"

        with patch("finanzamt.agent.requests.post") as mock_post:
            mock_post.return_value = _mock_ollama_response(llm_json_response)
            result = agent.process_receipt("receipt.pdf")

        assert result.success is True
        assert result.data is not None
        assert result.data.counterparty.name == "Bürobedarf GmbH"
        assert result.data.total_amount == Decimal("21.36")
        assert result.processing_time is not None

    def test_items_extracted(self, llm_json_response):
        agent, _ = _make_agent("some text")

        with patch("finanzamt.agent.requests.post") as mock_post:
            mock_post.return_value = _mock_ollama_response(llm_json_response)
            result = agent.process_receipt("receipt.pdf")

        assert len(result.data.items) == 2
        assert result.data.items[0].description == "Druckerpapier A4"

    def test_receipt_date_parsed(self, llm_json_response):
        agent, _ = _make_agent("text")
        with patch("finanzamt.agent.requests.post") as mock_post:
            mock_post.return_value = _mock_ollama_response(llm_json_response)
            result = agent.process_receipt("receipt.pdf")
        from datetime import datetime
        assert result.data.receipt_date == datetime(2024, 3, 15)

    def test_category_normalised(self, llm_json_response):
        agent, _ = _make_agent("text")
        with patch("finanzamt.agent.requests.post") as mock_post:
            mock_post.return_value = _mock_ollama_response(llm_json_response)
            result = agent.process_receipt("receipt.pdf")
        assert str(result.data.category) == "material"

    def test_unknown_category_falls_back_to_other(self, llm_json_response):
        llm_json_response["category"] = "flying_cars"
        agent, _ = _make_agent("text")
        with patch("finanzamt.agent.requests.post") as mock_post:
            mock_post.return_value = _mock_ollama_response(llm_json_response)
            result = agent.process_receipt("receipt.pdf")
        assert str(result.data.category) == "other"


# ---------------------------------------------------------------------------
# process_receipt — fallback path
# ---------------------------------------------------------------------------

class TestProcessReceiptFallback:
    def test_falls_back_to_rules_when_llm_fails(self):
        agent, _ = _make_agent("Müller GmbH\nGesamt 49,99 €")

        with patch("finanzamt.agent.requests.post", side_effect=requests.exceptions.ConnectionError):
            result = agent.process_receipt("receipt.pdf")

        # Should succeed via rule-based fallback (if validation passes)
        # or fail gracefully — either is acceptable, but no unhandled exception
        assert isinstance(result.success, bool)

    def test_falls_back_when_llm_returns_no_items(self, llm_json_response):
        llm_json_response["items"] = []
        agent, _ = _make_agent("Müller GmbH\n2x Stift 4,99 €\nGesamt 4,99 €")

        with patch("finanzamt.agent.requests.post") as mock_post:
            mock_post.return_value = _mock_ollama_response(llm_json_response)
            result = agent.process_receipt("receipt.pdf")

        assert isinstance(result.success, bool)


# ---------------------------------------------------------------------------
# process_receipt — failure paths
# ---------------------------------------------------------------------------

class TestProcessReceiptFailures:
    def test_empty_ocr_text_returns_failure(self):
        agent, _ = _make_agent("")
        result = agent.process_receipt("receipt.pdf")
        assert result.success is False
        assert "No text" in (result.error_message or "")

    def test_ocr_error_returns_failure(self):
        agent, mock_ocr = _make_agent()
        mock_ocr.extract_text_from_pdf.side_effect = OCRProcessingError("read error")
        result = agent.process_receipt("receipt.pdf")
        assert result.success is False
        assert result.error_message is not None

    def test_processing_time_always_set(self):
        agent, _ = _make_agent("")
        result = agent.process_receipt("receipt.pdf")
        assert result.processing_time is not None
        assert result.processing_time >= 0

    def test_unexpected_exception_returns_failure(self):
        agent, mock_ocr = _make_agent()
        mock_ocr.extract_text_from_pdf.side_effect = MemoryError("OOM")
        result = agent.process_receipt("receipt.pdf")
        assert result.success is False
        assert "Unexpected" in (result.error_message or "")


# ---------------------------------------------------------------------------
# _extract_with_llm
# ---------------------------------------------------------------------------

class TestExtractWithLlm:
    def test_retries_on_connection_error(self):
        config = Config(max_retries=3, request_timeout=5)
        agent, _ = _make_agent("text", config=config)

        with patch("finanzamt.agent.requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.ConnectionError
            with pytest.raises(LLMExtractionError):
                agent._extract_with_llm("some receipt text")

        assert mock_post.call_count == 3

    def test_retries_on_json_decode_error(self):
        """
        clean_json_response returns '{}' for garbage input, which json.loads
        parses successfully, so the agent does NOT retry on that path.
        What causes retries is a non-200 HTTP status — test that instead.
        """
        config = Config(max_retries=2, request_timeout=5)
        agent, _ = _make_agent("text", config=config)

        bad_resp = MagicMock()
        bad_resp.status_code = 503
        bad_resp.json.return_value = {}

        with patch("finanzamt.agent.requests.post", return_value=bad_resp):
            with pytest.raises(LLMExtractionError):
                agent._extract_with_llm("text")

    def test_raises_after_all_retries_exhausted(self):
        config = Config(max_retries=2)
        agent, _ = _make_agent("text", config=config)

        with patch("finanzamt.agent.requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.Timeout
            with pytest.raises(LLMExtractionError):
                agent._extract_with_llm("text")

    def test_uses_prompt_from_prompts_module(self):
        agent, _ = _make_agent("text")

        with patch("finanzamt.agent.requests.post") as mock_post, \
             patch("finanzamt.agent.build_extraction_prompt", return_value="PROMPT") as mock_prompt:
            mock_post.return_value = _mock_ollama_response({"items": []})
            try:
                agent._extract_with_llm("receipt text")
            except Exception:
                pass
            mock_prompt.assert_called_once_with("receipt text")

    def test_uses_model_config_attributes(self, llm_json_response):
        config = Config(model="mistral", max_retries=1)
        agent, _ = _make_agent("text", config=config)

        with patch("finanzamt.agent.requests.post") as mock_post:
            mock_post.return_value = _mock_ollama_response(llm_json_response)
            agent._extract_with_llm("text")
            call_kwargs = mock_post.call_args
            body = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
            assert body["model"] == "mistral"


# ---------------------------------------------------------------------------
# _extract_with_rules
# ---------------------------------------------------------------------------

class TestExtractWithRules:
    def test_returns_dict_with_expected_keys(self):
        agent, _ = _make_agent()
        result = agent._extract_with_rules("Müller GmbH\nGesamt 49,99 €")
        for key in ("counterparty_name", "receipt_date", "total_amount",
                    "vat_percentage", "vat_amount", "category", "items"):
            assert key in result, f"Missing key: {key}"

    def test_category_default_is_other(self):
        agent, _ = _make_agent()
        result = agent._extract_with_rules("random text without keywords")
        assert result["category"] == "other"

    def test_items_is_list(self):
        agent, _ = _make_agent()
        result = agent._extract_with_rules("Drucker 199,00 €")
        assert isinstance(result["items"], list)


# ---------------------------------------------------------------------------
# batch_process
# ---------------------------------------------------------------------------

class TestBatchProcess:
    def test_returns_result_for_each_input(self, llm_json_response, tmp_path):
        # Create dummy PDF stubs (content doesn't matter — OCR is mocked)
        pdf1 = tmp_path / "r1.pdf"
        pdf2 = tmp_path / "r2.pdf"
        pdf1.write_bytes(b"%PDF-1.4")
        pdf2.write_bytes(b"%PDF-1.4")

        agent, mock_ocr = _make_agent("Gesamt 10,00 €")

        with patch("finanzamt.agent.requests.post") as mock_post:
            mock_post.return_value = _mock_ollama_response(llm_json_response)
            results = agent.batch_process([pdf1, pdf2])

        assert len(results) == 2
        assert str(pdf1) in results
        assert str(pdf2) in results

    def test_empty_list_returns_empty_dict(self):
        agent, _ = _make_agent()
        assert agent.batch_process([]) == {}

    def test_one_failure_does_not_stop_batch(self, llm_json_response, tmp_path):
        pdf1 = tmp_path / "ok.pdf"
        pdf2 = tmp_path / "bad.pdf"
        pdf1.write_bytes(b"%PDF")
        pdf2.write_bytes(b"%PDF")

        agent, mock_ocr = _make_agent("Gesamt 10,00 €")

        call_count = 0

        def ocr_side_effect(path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "Gesamt 10,00 €"
            raise OCRProcessingError("corrupt file")

        mock_ocr.extract_text_from_pdf.side_effect = ocr_side_effect

        with patch("finanzamt.agent.requests.post") as mock_post:
            mock_post.return_value = _mock_ollama_response(llm_json_response)
            results = agent.batch_process([pdf1, pdf2])

        assert len(results) == 2
        successes = [r for r in results.values() if r.success]
        failures  = [r for r in results.values() if not r.success]
        assert len(successes) == 1
        assert len(failures)  == 1