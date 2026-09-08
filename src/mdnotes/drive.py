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


def list_folder_children(service, parent_id: str = "root") -> list[dict]:
    """Subfolders of parent_id ('root' for My Drive top level). For the setup folder browser."""
    result = service.files().list(
        q=f"mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false",
        fields="files(id, name)",
    ).execute()
    return sorted(result.get("files", []), key=lambda f: f["name"].lower())


def walk_folders(service, root_id: str) -> list[dict]:
    """Return every folder under root_id as a flat list of {id, name, path, parent_id}."""
    out: list[dict] = []

    def rec(folder_id, parent_id, prefix):
        subfolders, _ = list_items(service, folder_id)
        for s in subfolders:
            path = f"{prefix}/{s['name']}" if prefix else s["name"]
            out.append({"id": s["id"], "name": s["name"], "path": path, "parent_id": parent_id})
            rec(s["id"], s["id"], path)

    rec(root_id, None, "")
    return out


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
