# tests/test_drive.py
from unittest.mock import MagicMock, patch, call
from pathlib import Path
import pytest
from mdnotes.drive import list_goodnotes_pdfs, download_pdf, find_goodnotes_folder_id


def test_find_goodnotes_folder_id_returns_id(mock_drive_service):
    mock_drive_service.files().list().execute.return_value = {
        "files": [{"id": "folder123", "name": "GoodNotes 5"}]
    }
    result = find_goodnotes_folder_id(mock_drive_service, folder_name="GoodNotes 5")
    assert result == "folder123"


def test_find_goodnotes_folder_id_raises_when_not_found(mock_drive_service):
    mock_drive_service.files().list().execute.return_value = {"files": []}
    with pytest.raises(FileNotFoundError, match="GoodNotes 5"):
        find_goodnotes_folder_id(mock_drive_service, folder_name="GoodNotes 5")


def test_list_goodnotes_pdfs_returns_file_metadata(mock_drive_service):
    mock_drive_service.files().list().execute.return_value = {
        "files": [
            {"id": "abc", "name": "Math Notes.pdf", "modifiedTime": "2024-01-01T00:00:00.000Z"},
            {"id": "def", "name": "History.pdf", "modifiedTime": "2024-02-01T00:00:00.000Z"},
        ]
    }
    files = list_goodnotes_pdfs(mock_drive_service, folder_id="folder123")
    assert len(files) == 2
    assert files[0]["name"] == "Math Notes.pdf"


def test_download_pdf_writes_file(mock_drive_service, tmp_path):
    """download_pdf should write bytes to output_dir/<name>."""
    mock_media = MagicMock()
    mock_media.next_chunk.side_effect = [(None, False), (None, True)]
    mock_drive_service.files().get_media.return_value = mock_media

    with patch("mdnotes.drive.MediaIoBaseDownload") as MockDL:
        instance = MockDL.return_value
        instance.next_chunk.side_effect = [(None, False), (None, True)]

        path = download_pdf(
            mock_drive_service,
            file_id="abc",
            file_name="Math Notes.pdf",
            output_dir=tmp_path,
        )

    assert path == tmp_path / "Math Notes.pdf"
