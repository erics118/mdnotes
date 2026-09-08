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

    BFS the subtree one level at a time, batching each level's ids into an OR'd
    `in parents` query, so we fetch only folders under root_id -- not every folder in
    the Drive (a personal Drive has far more folders elsewhere).
    """
    out: list[dict] = []
    seen: set[str] = set()
    prefix_of: dict[str, str] = {root_id: ""}
    frontier = [root_id]

    while frontier:
        parents_set = set(frontier)
        found: list[dict] = []
        for i in range(0, len(frontier), 50):  # keep the OR clause a sane length
            batch = frontier[i:i + 50]
            clause = " or ".join(f"'{fid}' in parents" for fid in batch)
            found.extend(_list_all(
                service,
                q=f"({clause}) and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="nextPageToken, files(id, name, parents)",
            ))

        next_frontier: list[str] = []
        for f in sorted(found, key=lambda x: x["name"].lower()):
            if f["id"] in seen:  # guard against cycles and multi-parent folders
                continue
            parent = next((p for p in (f.get("parents") or []) if p in parents_set), None)
            if parent is None:
                continue
            seen.add(f["id"])
            prefix = prefix_of[parent]
            path = f"{prefix}/{f['name']}" if prefix else f["name"]
            out.append({"id": f["id"], "name": f["name"], "path": path,
                        "parent_id": None if parent == root_id else parent})
            prefix_of[f["id"]] = path
            next_frontier.append(f["id"])
        frontier = next_frontier

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
