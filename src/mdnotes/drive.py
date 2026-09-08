# src/mdnotes/drive.py
import os
from pathlib import Path
from googleapiclient.http import MediaIoBaseDownload


def _escape_q(value: str) -> str:
    """Escape a string literal for a Drive query (backslash and single-quote)."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _list_all(service, **kwargs) -> list[dict]:
    """files().list with full pagination (Drive returns <=100 per page by default)."""
    items: list[dict] = []
    page_token = None
    while True:
        resp = service.files().list(pageSize=1000, pageToken=page_token, **kwargs).execute()
        items.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return items


def find_goodnotes_folder_id(service, folder_name: str = "GoodNotes 5") -> str:
    """Return the Drive folder ID for the GoodNotes sync folder."""
    result = service.files().list(
        q=f"mimeType='application/vnd.google-apps.folder' and name='{_escape_q(folder_name)}' and trashed=false",
        fields="files(id, name)",
    ).execute()
    files = result.get("files", [])
    if not files:
        raise FileNotFoundError(f"Google Drive folder '{folder_name}' not found")
    return files[0]["id"]


def list_items(service, folder_id: str) -> tuple[list[dict], list[dict]]:
    """Return (subfolders, pdfs) inside folder_id, both sorted by name."""
    items = _list_all(
        service,
        q=f"'{folder_id}' in parents and trashed=false and ("
          f"mimeType='application/vnd.google-apps.folder' or mimeType='application/pdf')",
        fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
    )
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
    items = _list_all(
        service,
        q=f"mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false",
        fields="nextPageToken, files(id, name)",
    )
    return sorted(items, key=lambda f: f["name"].lower())


def walk_folders(service, root_id: str) -> list[dict]:
    """Return every folder under root_id as a flat list of {id, name, path, parent_id}.

    Fetches all folders in one paginated query and builds the subtree in memory,
    instead of a Drive round-trip per folder (which is very slow for large trees).
    """
    children: dict[str, list[dict]] = {}
    page_token = None
    while True:
        resp = service.files().list(
            q="mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="nextPageToken, files(id, name, parents)",
            pageSize=1000,
            pageToken=page_token,
        ).execute()
        for f in resp.get("files", []):
            for parent in f.get("parents") or []:
                children.setdefault(parent, []).append(f)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    out: list[dict] = []
    seen: set[str] = set()

    def rec(folder_id, parent_id, prefix):
        for s in sorted(children.get(folder_id, []), key=lambda x: x["name"].lower()):
            if s["id"] in seen:  # guard against cycles and multi-parent folders
                continue
            seen.add(s["id"])
            path = f"{prefix}/{s['name']}" if prefix else s["name"]
            out.append({"id": s["id"], "name": s["name"], "path": path, "parent_id": parent_id})
            rec(s["id"], s["id"], path)

    rec(root_id, None, "")
    return out


def download_pdf(service, file_id: str, file_name: str, output_dir: Path) -> Path:
    """Download a Drive file by ID to output_dir. Returns the local path.

    Writes to a .part file first, then os.replace, so a dropped download never
    overwrites a good PDF with a truncated one.
    """
    dest = output_dir / file_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    request = service.files().get_media(fileId=file_id)
    try:
        with open(part, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        os.replace(part, dest)
    except BaseException:
        try:
            os.unlink(part)
        except OSError:
            pass
        raise
    return dest
