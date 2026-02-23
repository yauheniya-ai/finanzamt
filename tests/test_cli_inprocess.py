"""
tests/test_cli_inprocess.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
In-process tests for FinanzamtCLI with FinanceAgent fully mocked.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from finanzamt.cli import FinanzamtCLI


class TestFinanzamtCLI:

    def test_print_version(self, capsys):
        cli = FinanzamtCLI()
        cli.print_version()
        out = capsys.readouterr().out
        assert "finanzamt version" in out

    def test_process_receipt_success(self, mocker, tmp_path):
        cli = FinanzamtCLI()

        mock_agent_cls = mocker.patch("finanzamt.cli.FinanceAgent")
        mock_instance  = mock_agent_cls.return_value

        mock_result = mocker.Mock()
        mock_result.success   = True
        mock_result.duplicate = False
        mock_result.data.receipt_type.__str__ = lambda self: "purchase"
        mock_result.data.counterparty.name    = "Test GmbH"
        mock_result.data.total_amount         = 119
        mock_result.data.to_json.return_value = '{"vendor": "Test GmbH"}'
        mock_instance.process_receipt.return_value = mock_result

        input_dir = tmp_path
        (input_dir / "test.pdf").write_text("dummy", encoding="utf-8")

        rc = cli.process_receipt("test", input_dir)
        assert rc == 0
        mock_instance.process_receipt.assert_called_once()

    def test_process_receipt_duplicate(self, mocker, tmp_path):
        cli = FinanzamtCLI()

        mock_agent_cls = mocker.patch("finanzamt.cli.FinanceAgent")
        mock_instance  = mock_agent_cls.return_value

        mock_result = mocker.Mock()
        mock_result.success     = True
        mock_result.duplicate   = True
        mock_result.existing_id = "abc123"
        mock_result.data.counterparty.name = "Test GmbH"
        mock_instance.process_receipt.return_value = mock_result

        input_dir = tmp_path
        (input_dir / "test.pdf").write_text("dummy", encoding="utf-8")

        rc = cli.process_receipt("test", input_dir)
        assert rc == 0   # duplicate is not a failure

    def test_process_receipt_missing_file(self, tmp_path):
        cli = FinanzamtCLI()
        rc = cli.process_receipt("nonexistent", tmp_path)
        assert rc == 1

    def test_batch_process_mock(self, mocker, tmp_path, capsys):
        cli = FinanzamtCLI()

        mock_agent_cls = mocker.patch("finanzamt.cli.FinanceAgent")
        mock_instance  = mock_agent_cls.return_value

        mock_result = mocker.Mock()
        mock_result.success      = True
        mock_result.duplicate    = False
        mock_result.data.total_amount   = 10
        mock_result.data.vat_amount     = 2
        mock_result.data.category       = "food"
        mock_result.data.items          = []
        mock_result.data.receipt_date   = None
        mock_result.data.receipt_type.__str__ = lambda self: "purchase"
        mock_result.data.counterparty.name    = "Vendor GmbH"
        mock_result.data.vat_percentage       = 19
        mock_result.processing_time           = 1.5
        mock_result.to_dict.return_value      = {"success": True}
        mock_instance.process_receipt.return_value = mock_result

        input_dir = tmp_path
        (input_dir / "a.pdf").write_text("dummy", encoding="utf-8")
        (input_dir / "b.pdf").write_text("dummy", encoding="utf-8")

        rc = cli.batch_process(input_dir)
        out = capsys.readouterr().out

        assert rc == 0
        assert "BATCH PROCESSING REPORT" in out
        assert "Vendor GmbH" in out

    def test_batch_process_no_pdfs(self, tmp_path):
        cli = FinanzamtCLI()
        rc = cli.batch_process(tmp_path)
        assert rc == 1