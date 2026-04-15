# src/mdnotes/drive.py
import io
from pathlib import Path
from googleapiclient.http import MediaIoBaseDownload


def find_goodnotes_folder_id(service, folder_name: str = "GoodNotes 5") -> str:
    """Return the Drive folder ID for the GoodNotes sync folder."""
    result = service.files().list(
        q=f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false",
        fields="files(id, name)",
    ).execute()
    files = result.get("files", [])
    if not files:
        raise FileNotFoundError(f"Google Drive folder '{folder_name}' not found")
    return files[0]["id"]


def list_goodnotes_pdfs(service, folder_id: str) -> list[dict]:
    """Return list of PDF file metadata dicts inside folder_id."""
    result = service.files().list(
        q=f"mimeType='application/pdf' and '{folder_id}' in parents and trashed=false",
        fields="files(id, name, modifiedTime)",
    ).execute()
    return result.get("files", [])


def list_items(service, folder_id: str) -> tuple[list[dict], list[dict]]:
    """Return (subfolders, pdfs) inside folder_id, both sorted by name."""
    result = service.files().list(
        q=f"'{folder_id}' in parents and trashed=false and ("
          f"mimeType='application/vnd.google-apps.folder' or mimeType='application/pdf')",
        fields="files(id, name, mimeType, modifiedTime)",
    ).execute()
    items = result.get("files", [])
    folders = sorted(
        [f for f in items if f["mimeType"] == "application/vnd.google-apps.folder"],
        key=lambda f: f["name"],
    )
    pdfs = sorted(
        [f for f in items if f["mimeType"] == "application/pdf"],
        key=lambda f: f["name"],
    )
    return folders, pdfs


def download_pdf(service, file_id: str, file_name: str, output_dir: Path) -> Path:
    """Download a Drive file by ID to output_dir. Returns the local path."""
    dest = output_dir / file_name
    request = service.files().get_media(fileId=file_id)
    with open(dest, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    return dest
