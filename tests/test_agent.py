"""
tests/test_agent.py
~~~~~~~~~~~~~~~~~~~~
Tests for finanzamt.agents.agent — FinanceAgent with all external I/O mocked.

The new pipeline makes 4 sequential LLM calls (one per agent).
We mock finanzamt.agents.llm_caller.requests.post and return appropriate
JSON for each call via side_effect.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from finanzamt.agents.agent import FinanceAgent
from finanzamt.agents.config import Config, AgentsConfig
from finanzamt.exceptions import InvalidReceiptError, OCRProcessingError
from finanzamt.models import ReceiptData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(ocr_text: str = "") -> tuple[FinanceAgent, MagicMock]:
    """Return (agent, mock_ocr) with OCR pre-configured to return ocr_text."""
    with patch("finanzamt.agents.agent.OCRProcessor") as MockOCR:
        mock_ocr = MockOCR.return_value
        mock_ocr.extract_text_from_pdf.return_value = ocr_text
        agent = FinanceAgent(db_path=None)
        agent.ocr = mock_ocr
    return agent, mock_ocr


def _ollama_resp(data: dict) -> MagicMock:
    """Build a mock requests.Response returning data as Ollama JSON payload."""
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"response": json.dumps(data)}
    return m


def _four_responses(a1, a2, a3, a4):
    """Return a side_effect list for 4 sequential requests.post calls."""
    return [_ollama_resp(a1), _ollama_resp(a2), _ollama_resp(a3), _ollama_resp(a4)]


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestInit:
    def test_default_agents_config_used(self):
        with patch("finanzamt.agents.agent.OCRProcessor"):
            agent = FinanceAgent(db_path=None)
        assert isinstance(agent.agents_cfg, AgentsConfig)

    def test_custom_agents_config_accepted(self):
        cfg = AgentsConfig(agent_model="mistral")
        with patch("finanzamt.agents.agent.OCRProcessor"):
            agent = FinanceAgent(agents_cfg=cfg, db_path=None)
        assert agent.agents_cfg.agent_model == "mistral"

    def test_no_basicconfig_called(self):
        import logging
        root = logging.getLogger()
        original_handlers = list(root.handlers)
        with patch("finanzamt.agents.agent.OCRProcessor"):
            FinanceAgent(db_path=None)
        assert list(root.handlers) == original_handlers


# ---------------------------------------------------------------------------
# process_receipt — success paths
# ---------------------------------------------------------------------------

class TestProcessReceiptSuccess:
    def test_successful_4agent_extraction(
        self, agent1_response, agent2_response, agent3_response, agent4_response
    ):
        agent, mock_ocr = _make_agent("Bürobedarf GmbH\nGesamt 21,36 €")

        with patch("finanzamt.agents.llm_caller.requests.post") as mock_post:
            mock_post.side_effect = _four_responses(
                agent1_response, agent2_response, agent3_response, agent4_response
            )
            result = agent.process_receipt("receipt.pdf")

        assert result.success is True
        assert result.data is not None
        assert result.data.counterparty.name == "Bürobedarf GmbH"
        assert result.data.total_amount == Decimal("21.36")
        assert result.processing_time is not None

    def test_exactly_4_llm_calls_made(
        self, agent1_response, agent2_response, agent3_response, agent4_response
    ):
        agent, _ = _make_agent("some text")

        with patch("finanzamt.agents.llm_caller.requests.post") as mock_post:
            mock_post.side_effect = _four_responses(
                agent1_response, agent2_response, agent3_response, agent4_response
            )
            agent.process_receipt("receipt.pdf")

        assert mock_post.call_count == 4

    def test_items_extracted(
        self, agent1_response, agent2_response, agent3_response, agent4_response
    ):
        agent, _ = _make_agent("some text")

        with patch("finanzamt.agents.llm_caller.requests.post") as mock_post:
            mock_post.side_effect = _four_responses(
                agent1_response, agent2_response, agent3_response, agent4_response
            )
            result = agent.process_receipt("receipt.pdf")

        assert len(result.data.items) == 2
        assert result.data.items[0].description == "Druckerpapier A4"

    def test_receipt_date_parsed(
        self, agent1_response, agent2_response, agent3_response, agent4_response
    ):
        agent, _ = _make_agent("text")
        with patch("finanzamt.agents.llm_caller.requests.post") as mock_post:
            mock_post.side_effect = _four_responses(
                agent1_response, agent2_response, agent3_response, agent4_response
            )
            result = agent.process_receipt("receipt.pdf")
        from datetime import datetime
        assert result.data.receipt_date == datetime(2024, 3, 15)

    def test_category_normalised(
        self, agent1_response, agent2_response, agent3_response, agent4_response
    ):
        agent, _ = _make_agent("text")
        with patch("finanzamt.agents.llm_caller.requests.post") as mock_post:
            mock_post.side_effect = _four_responses(
                agent1_response, agent2_response, agent3_response, agent4_response
            )
            result = agent.process_receipt("receipt.pdf")
        assert str(result.data.category) == "material"

    def test_unknown_category_falls_back_to_other(
        self, agent2_response, agent3_response, agent4_response
    ):
        bad_a1 = {"receipt_number": None, "receipt_date": "2024-03-15", "category": "flying_cars"}
        agent, _ = _make_agent("text")
        with patch("finanzamt.agents.llm_caller.requests.post") as mock_post:
            mock_post.side_effect = _four_responses(bad_a1, agent2_response, agent3_response, agent4_response)
            result = agent.process_receipt("receipt.pdf")
        assert str(result.data.category) == "other"

    def test_no_items_in_agent4_response(
        self, agent1_response, agent2_response, agent3_response
    ):
        a4_empty = {"items": []}
        agent, _ = _make_agent("text")
        with patch("finanzamt.agents.llm_caller.requests.post") as mock_post:
            mock_post.side_effect = _four_responses(
                agent1_response, agent2_response, agent3_response, a4_empty
            )
            result = agent.process_receipt("receipt.pdf")
        assert result.data.items == []


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

    def test_llm_connection_error_still_produces_result(self):
        """LLM failure → all agents return None → ReceiptData with nulls built anyway."""
        import requests as req
        agent, _ = _make_agent("Müller GmbH\nGesamt 49,99 €")
        with patch("finanzamt.agents.llm_caller.requests.post",
                   side_effect=req.exceptions.ConnectionError):
            result = agent.process_receipt("receipt.pdf")
        # No unhandled exception — result is either success or graceful failure
        assert isinstance(result.success, bool)


# ---------------------------------------------------------------------------
# batch_process
# ---------------------------------------------------------------------------

class TestBatchProcess:
    def test_returns_result_for_each_input(
        self, tmp_path, agent1_response, agent2_response, agent3_response, agent4_response
    ):
        pdf1 = tmp_path / "r1.pdf"
        pdf2 = tmp_path / "r2.pdf"
        pdf1.write_bytes(b"%PDF-1.4")
        pdf2.write_bytes(b"%PDF-1.4")

        agent, _ = _make_agent("Gesamt 10,00 €")

        with patch("finanzamt.agents.llm_caller.requests.post") as mock_post:
            mock_post.side_effect = (
                _four_responses(agent1_response, agent2_response, agent3_response, agent4_response)
                + _four_responses(agent1_response, agent2_response, agent3_response, agent4_response)
            )
            results = agent.batch_process([pdf1, pdf2])

        assert len(results) == 2
        assert str(pdf1) in results
        assert str(pdf2) in results

    def test_empty_list_returns_empty_dict(self):
        agent, _ = _make_agent()
        assert agent.batch_process([]) == {}

    def test_one_failure_does_not_stop_batch(
        self, tmp_path, agent1_response, agent2_response, agent3_response, agent4_response
    ):
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

        with patch("finanzamt.agents.llm_caller.requests.post") as mock_post:
            mock_post.side_effect = _four_responses(
                agent1_response, agent2_response, agent3_response, agent4_response
            )
            results = agent.batch_process([pdf1, pdf2])

        assert len(results) == 2
        assert len([r for r in results.values() if r.success]) == 1
        assert len([r for r in results.values() if not r.success]) == 1