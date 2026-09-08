# tests/test_pipeline.py
from pathlib import Path
from datetime import timezone
from unittest.mock import MagicMock, patch, call
import pytest
from mdnotes.pipeline import run_pipeline, PipelineResult, _is_up_to_date, _drive_mtime


def _file_meta(name="Math Notes.pdf", mtime="2024-01-01T00:00:00.000000Z", fid="f1"):
    return {"id": fid, "name": name, "modifiedTime": mtime}


def test_run_pipeline_creates_markdown_files(tmp_path):
    """End-to-end: one PDF in root produces one .md file."""
    pdf_path = tmp_path / "Math Notes.pdf"
    pdf_path.write_bytes(b"%PDF fake")

    mock_service = MagicMock()

    with patch("mdnotes.pipeline.find_goodnotes_folder_id", return_value="folder1"), \
         patch("mdnotes.pipeline.list_items", side_effect=[
             # root: no subfolders, one PDF
             ([], [_file_meta()]),
         ]), \
         patch("mdnotes.pipeline.download_pdf", return_value=pdf_path), \
         patch("mdnotes.pipeline.pdf_page_count", return_value=1), \
         patch("mdnotes.pipeline.pdf_page_hash", return_value="abc123"), \
         patch("mdnotes.pipeline.rasterize_page", return_value=b"img"), \
         patch("mdnotes.pipeline.transcribe_page", return_value="# Math Notes\n- item"), \
         patch("builtins.input", return_value="y"):

        result = run_pipeline(
            service=mock_service,
            output_dir=tmp_path,
            folder_name="GoodNotes 5",
            cache_path=tmp_path / "cache.json",
        )

    md_path = tmp_path / "Math Notes.md"
    assert md_path.exists()
    text = md_path.read_text()
    assert text.startswith("---\n")  # YAML frontmatter header
    assert "# Math Notes\n- item" in text
    assert result.processed == ["Math Notes.pdf"]
    assert result.skipped == []


def test_sync_no_prompt_auto_indexes(tmp_path):
    """assume_yes syncs without prompting and indexes each finalized note."""
    pdf_path = tmp_path / "Math Notes.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    idx = MagicMock()

    with patch("mdnotes.pipeline.find_goodnotes_folder_id", return_value="folder1"), \
         patch("mdnotes.pipeline.list_items", side_effect=[([], [_file_meta()])]), \
         patch("mdnotes.pipeline.download_pdf", return_value=pdf_path), \
         patch("mdnotes.pipeline.pdf_page_count", return_value=1), \
         patch("mdnotes.pipeline.pdf_page_hash", return_value="h"), \
         patch("mdnotes.pipeline.rasterize_page", return_value=b"img"), \
         patch("mdnotes.pipeline.transcribe_page", return_value="# body"), \
         patch("mdnotes.index.NoteIndex", return_value=idx):
        # no builtins.input patch: assume_yes must not prompt
        result = run_pipeline(
            service=MagicMock(), output_dir=tmp_path, folder_name="GoodNotes 5",
            cache_path=tmp_path / "c.json", assume_yes=True, index_path=tmp_path / "idx.db",
        )

    assert result.processed == ["Math Notes.pdf"]
    idx.upsert_note.assert_called_once()
    assert idx.upsert_note.call_args[0][0] == "Math Notes.md"  # root-relative note_id


def test_run_pipeline_skips_up_to_date_files(tmp_path):
    """If .md has a synced header matching Drive modifiedTime, skip the file."""
    mtime = "2024-01-01T00:00:00.000000Z"
    md_path = tmp_path / "Math Notes.md"
    md_path.write_text(f"<!-- mdnotes: synced: {mtime} -->\n\n# already done")

    mock_service = MagicMock()

    with patch("mdnotes.pipeline.find_goodnotes_folder_id", return_value="folder1"), \
         patch("mdnotes.pipeline.list_items", return_value=([], [_file_meta(mtime=mtime)])), \
         patch("mdnotes.pipeline.download_pdf") as mock_dl, \
         patch("builtins.input", return_value="n"):

        result = run_pipeline(
            service=mock_service,
            output_dir=tmp_path,
            folder_name="GoodNotes 5",
            cache_path=tmp_path / "cache.json",
        )

    mock_dl.assert_not_called()
    assert result.skipped == ["Math Notes.pdf"]


def test_is_up_to_date_uses_synced_header(tmp_path):
    """_is_up_to_date returns True when synced header matches Drive mtime."""
    mtime = "2024-06-01T00:00:00.000000Z"
    md = tmp_path / "test.md"
    md.write_text(f"<!-- mdnotes: synced: {mtime} -->\n\ncontent")
    assert _is_up_to_date({"modifiedTime": mtime}, md) is True


def test_is_up_to_date_false_when_drive_newer(tmp_path):
    """_is_up_to_date returns False when Drive has a newer mtime."""
    md = tmp_path / "test.md"
    md.write_text("<!-- mdnotes: synced: 2024-01-01T00:00:00.000000Z -->\n\ncontent")
    assert _is_up_to_date({"modifiedTime": "2025-01-01T00:00:00.000000Z"}, md) is False


def test_is_up_to_date_false_for_old_format_without_provenance(tmp_path):
    """A note with no frontmatter/synced header (old single-block format) is re-synced."""
    md = tmp_path / "old.md"
    md.write_text("# 1/23\n\nSome transcription with no markers at all.")
    assert _is_up_to_date({"modifiedTime": "2024-01-01T00:00:00.000000Z"}, md) is False


def test_is_up_to_date_false_for_in_progress(tmp_path):
    """_is_up_to_date returns False for files with the in-progress marker."""
    md = tmp_path / "test.md"
    md.write_text("# page\n\n<!-- mdnotes: in progress: 2024-01-01T00:00:00.000000Z -->")
    assert _is_up_to_date({"modifiedTime": "2024-01-01T00:00:00.000000Z"}, md) is False
