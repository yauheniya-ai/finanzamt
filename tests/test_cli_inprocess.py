import sys
from pathlib import Path
import pytest
# Add src/finanzamt to sys.path for import resolution
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from finanzamt.cli import FinanzamtCLI

class TestFinanzamtCLI:
    def test_print_version(self, capsys):
        cli = FinanzamtCLI()
        cli.print_version()
        out = capsys.readouterr().out
        assert "finanzamt version" in out

    def test_process_receipt_mock(self, mocker, tmp_path):
        cli = FinanzamtCLI()
        # Mock FinanceAgent.process_receipt
        mock_agent = mocker.patch('finanzamt.cli.FinanceAgent')
        mock_instance = mock_agent.return_value
        mock_result = mocker.Mock()
        mock_result.success = True
        mock_result.data.to_json.return_value = '{"foo": "bar"}'
        mock_instance.process_receipt.return_value = mock_result
        input_dir = tmp_path
        (input_dir / "test.pdf").write_text("dummy", encoding="utf-8")
        cli.process_receipt("test", input_dir)
        out = (input_dir / "test_extracted.json").read_text()
        assert 'foo' in out

    def test_batch_process_mock(self, mocker, tmp_path, capsys):
        cli = FinanzamtCLI()
        mock_agent = mocker.patch('finanzamt.cli.FinanceAgent')
        mock_instance = mock_agent.return_value
        mock_result = mocker.Mock()
        mock_result.success = True
        mock_result.data.total_amount = 10
        mock_result.data.vat_amount = 2
        mock_result.data.category = 'Food'
        mock_result.data.items = []
        mock_result.data.receipt_date = None
        mock_result.data.vendor = 'Vendor'
        mock_result.data.vat_percentage = 19
        mock_result.processing_time = 1.5
        mock_result.data.to_json.return_value = '{"foo": "bar"}'
        mock_result.to_dict.return_value = {'success': True}
        mock_instance.process_receipt.return_value = mock_result
        input_dir = tmp_path
        (input_dir / "a.pdf").write_text("dummy", encoding="utf-8")
        (input_dir / "b.pdf").write_text("dummy", encoding="utf-8")
        cli.batch_process(input_dir)
        out = capsys.readouterr().out
        assert 'BATCH PROCESSING REPORT' in out
        assert 'Food' in out
        assert 'Vendor' in out
