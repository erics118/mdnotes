# tests/test_pipeline.py
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from mdnotes.pipeline import run_pipeline, PipelineResult


def test_run_pipeline_creates_markdown_files(tmp_path):
    """End-to-end: one PDF produces one .md file."""
    pdf_path = tmp_path / "Math Notes.pdf"
    pdf_path.write_bytes(b"%PDF fake")

    mock_service = MagicMock()

    with patch("mdnotes.pipeline.find_goodnotes_folder_id", return_value="folder1"), \
         patch("mdnotes.pipeline.list_goodnotes_pdfs", return_value=[
             {"id": "f1", "name": "Math Notes.pdf", "modifiedTime": "2024-01-01T00:00:00.000Z"}
         ]), \
         patch("mdnotes.pipeline.download_pdf", return_value=pdf_path), \
         patch("mdnotes.pipeline.rasterize_pdf", return_value=[(1, b"img")]), \
         patch("mdnotes.pipeline.transcribe_pdf_pages", return_value="# Math Notes\n- item"):

        result = run_pipeline(
            service=mock_service,
            output_dir=tmp_path,
            cache_path=tmp_path / "cache.json",
        )

    md_path = tmp_path / "Math Notes.md"
    assert md_path.exists()
    assert md_path.read_text() == "# Math Notes\n- item"
    assert result.processed == ["Math Notes.pdf"]
    assert result.skipped == []


def test_run_pipeline_skips_up_to_date_files(tmp_path):
    """If .md exists and is newer than Drive modifiedTime, skip the file."""
    md_path = tmp_path / "Math Notes.md"
    md_path.write_text("already done")

    import os, time
    # set mtime to "now" so it's newer than the Drive timestamp
    os.utime(md_path, None)

    mock_service = MagicMock()

    with patch("mdnotes.pipeline.find_goodnotes_folder_id", return_value="folder1"), \
         patch("mdnotes.pipeline.list_goodnotes_pdfs", return_value=[
             {"id": "f1", "name": "Math Notes.pdf", "modifiedTime": "2020-01-01T00:00:00.000Z"}
         ]), \
         patch("mdnotes.pipeline.download_pdf") as mock_dl, \
         patch("mdnotes.pipeline.rasterize_pdf"), \
         patch("mdnotes.pipeline.transcribe_pdf_pages"):

        result = run_pipeline(
            service=mock_service,
            output_dir=tmp_path,
            cache_path=tmp_path / "cache.json",
        )

    mock_dl.assert_not_called()
    assert result.skipped == ["Math Notes.pdf"]
