# tests/test_cli.py
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from mdnotes.cli import main


def test_sync_command_exists():
    runner = CliRunner()
    result = runner.invoke(main, ["sync", "--help"])
    assert result.exit_code == 0
    assert "--output-dir" in result.output
    assert "--folder-name" in result.output
    assert "--dpi" in result.output


def test_sync_command_runs_pipeline(tmp_path):
    mock_result = MagicMock()
    mock_result.processed = ["A.pdf"]
    mock_result.skipped = []
    mock_result.errors = []

    with patch("mdnotes.cli.get_drive_service") as mock_auth, \
         patch("mdnotes.cli.run_pipeline", return_value=mock_result) as mock_pipeline:
        runner = CliRunner()
        result = runner.invoke(main, ["sync", "--output-dir", str(tmp_path)])

    assert result.exit_code == 0
    mock_pipeline.assert_called_once()
    assert "A.pdf" in result.output


def test_sync_command_reports_errors(tmp_path):
    mock_result = MagicMock()
    mock_result.processed = []
    mock_result.skipped = []
    mock_result.errors = ["B.pdf: rasterize failed"]

    with patch("mdnotes.cli.get_drive_service"), \
         patch("mdnotes.cli.run_pipeline", return_value=mock_result):
        runner = CliRunner()
        result = runner.invoke(main, ["sync", "--output-dir", str(tmp_path)])

    assert "B.pdf: rasterize failed" in result.output
