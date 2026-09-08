# tests/test_pipeline.py
from pathlib import Path
from datetime import timezone
from unittest.mock import MagicMock, patch, call
import pytest
from mdnotes.pipeline import run_pipeline, PipelineResult, _is_up_to_date, _drive_mtime
from mdnotes.prefs import SyncPrefs


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


def test_sync_excludes_named_folder(tmp_path):
    """--exclude skips a folder entirely, even under --no-prompt."""
    pdf_path = tmp_path / "note.pdf"
    pdf_path.write_bytes(b"%PDF")

    with patch("mdnotes.pipeline.find_goodnotes_folder_id", return_value="root"), \
         patch("mdnotes.pipeline.list_items", side_effect=[
             ([{"id": "a", "name": "MATH 2210"}, {"id": "b", "name": "CS 3110"}], []),
             ([], [_file_meta(name="note.pdf", fid="f2")]),  # contents of MATH 2210
         ]), \
         patch("mdnotes.pipeline.download_pdf", return_value=pdf_path), \
         patch("mdnotes.pipeline.pdf_page_count", return_value=1), \
         patch("mdnotes.pipeline.pdf_page_hash", return_value="h"), \
         patch("mdnotes.pipeline.rasterize_page", return_value=b"img"), \
         patch("mdnotes.pipeline.transcribe_page", return_value="# b"):
        result = run_pipeline(
            service=MagicMock(), output_dir=tmp_path, folder_name="GoodNotes",
            cache_path=tmp_path / "c.json", assume_yes=True, exclude={"CS 3110"},
        )

    assert "CS 3110" in result.skipped
    assert "note.pdf" in result.processed


def test_noninteractive_honors_prefs_default_ignore(tmp_path):
    """Non-interactive sync: pref YES syncs, pref NO/unset skipped, no input() called."""
    pdf_path = tmp_path / "note.pdf"
    pdf_path.write_bytes(b"%PDF")

    prefs = SyncPrefs(path=tmp_path / "prefs.json")
    prefs.set("a", "yes", name="MATH 2210")   # sync
    prefs.set("b", "no", name="CS 3110")       # ignore
    # folder "c" (MATH 4130) has no pref -> default ignore

    with patch("mdnotes.pipeline.find_goodnotes_folder_id", return_value="root"), \
         patch("mdnotes.pipeline.SyncPrefs", return_value=prefs), \
         patch("mdnotes.pipeline.list_items", side_effect=[
             ([{"id": "a", "name": "MATH 2210"}, {"id": "b", "name": "CS 3110"},
               {"id": "c", "name": "MATH 4130"}], []),                 # root
             ([], [_file_meta(name="note.pdf", fid="f2")]),            # MATH 2210 (synced)
             ([], [_file_meta(name="x.pdf", fid="f3")]),               # CS 3110 (non-empty, ignored)
             ([], [_file_meta(name="y.pdf", fid="f4")]),               # MATH 4130 (non-empty, default ignore)
         ]), \
         patch("mdnotes.pipeline.download_pdf", return_value=pdf_path), \
         patch("mdnotes.pipeline.pdf_page_count", return_value=1), \
         patch("mdnotes.pipeline.pdf_page_hash", return_value="h"), \
         patch("mdnotes.pipeline.rasterize_page", return_value=b"img"), \
         patch("mdnotes.pipeline.transcribe_page", return_value="# b"):
        result = run_pipeline(
            service=MagicMock(), output_dir=tmp_path, folder_name="GoodNotes",
            cache_path=tmp_path / "c.json", interactive=False,
        )

    assert "note.pdf" in result.processed        # MATH 2210 (yes) synced
    assert "CS 3110" in result.skipped           # explicit no
    assert "MATH 4130" in result.skipped         # unset -> default ignore


def test_run_pipeline_uses_root_id_directly(tmp_path):
    with patch("mdnotes.pipeline.find_goodnotes_folder_id") as find, \
         patch("mdnotes.pipeline.list_items", return_value=([], [])):
        run_pipeline(service=MagicMock(), output_dir=tmp_path, folder_name="x",
                     cache_path=tmp_path / "c.json", interactive=False, root_id="ROOT")
    find.assert_not_called()


def test_should_stop_halts_before_processing(tmp_path):
    with patch("mdnotes.pipeline.find_goodnotes_folder_id", return_value="root"), \
         patch("mdnotes.pipeline.list_items", return_value=([{"id": "a", "name": "MATH 2210"}], [])):
        result = run_pipeline(service=MagicMock(), output_dir=tmp_path, folder_name="GoodNotes",
                              cache_path=tmp_path / "c.json", interactive=False, should_stop=lambda: True)
    assert result.processed == []


def test_progress_events_emitted(tmp_path):
    pdf = tmp_path / "note.pdf"
    pdf.write_bytes(b"%PDF")
    events = []
    with patch("mdnotes.pipeline.find_goodnotes_folder_id", return_value="root"), \
         patch("mdnotes.pipeline.list_items", side_effect=[([], [_file_meta(name="note.pdf", fid="f2")])]), \
         patch("mdnotes.pipeline.download_pdf", return_value=pdf), \
         patch("mdnotes.pipeline.pdf_page_count", return_value=1), \
         patch("mdnotes.pipeline.pdf_page_hash", return_value="h"), \
         patch("mdnotes.pipeline.rasterize_page", return_value=b"img"), \
         patch("mdnotes.pipeline.transcribe_page", return_value="# b"):
        run_pipeline(service=MagicMock(), output_dir=tmp_path, folder_name="GoodNotes",
                     cache_path=tmp_path / "c.json", assume_yes=True,
                     progress=lambda e: events.append(e["type"]))
    assert "file" in events and "page" in events and "done" in events


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
