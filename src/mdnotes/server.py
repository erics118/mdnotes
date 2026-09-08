import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from mdnotes.config import DEFAULT_NOTES, anthropic_key, voyage_key
from mdnotes.drive import list_folder_children, walk_folders
from mdnotes.index import DEFAULT_INDEX, NoteIndex
from mdnotes.pipeline import DEFAULT_CACHE, run_pipeline
from mdnotes.prefs import NO, SyncPrefs, YES
from mdnotes.search import search as run_search

INDEX_PATH = Path(os.environ.get("MDNOTES_INDEX", str(DEFAULT_INDEX)))
PASSWORD = os.environ.get("MDNOTES_PASSWORD")
if PASSWORD is not None:
    try:
        PASSWORD.encode("ascii")
    except UnicodeEncodeError as e:
        # HTTP Basic (btoa on the client, FastAPI's decoder) is ASCII-only
        raise RuntimeError("MDNOTES_PASSWORD must be ASCII") from e

app = FastAPI(title="mdnotes")
security = HTTPBasic(auto_error=False)

# background job state (single-user app)
_sync = {"running": False, "started": None, "result": None, "error": None,
         "progress": None, "stopping": False}
_auth = {"running": False, "error": None}


def require_auth(request: Request, creds: HTTPBasicCredentials | None = Depends(security)):
    if PASSWORD is None:
        return
    # Basic auth only; a ?pw= query param would leak the password into logs and history
    supplied = creds.password if creds else None
    if supplied is None or not secrets.compare_digest(supplied, PASSWORD):
        raise HTTPException(status_code=401, detail="unauthorized",
                            headers={"WWW-Authenticate": "Basic"})


def block_cross_site(request: Request):
    """Reject cross-site state-changing requests (CSRF) using the Fetch Metadata header.

    A hostile page can POST to the default passwordless localhost server; the SPA's own
    requests are same-origin. Absent header (non-browser clients, tests) is allowed.
    """
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(status_code=403, detail="cross-site request blocked")


def _prefs() -> SyncPrefs:
    return SyncPrefs()


def _folder_name() -> str | None:
    # display name of the chosen notes folder
    return _prefs().get_setting("folder_name") or os.environ.get("MDNOTES_FOLDER")


def _folder_id() -> str | None:
    # id of the notes folder chosen in the setup wizard (authoritative; handles nesting)
    return _prefs().get_setting("folder_id") or os.environ.get("MDNOTES_FOLDER_ID")


def _output_dir() -> Path:
    return Path(_prefs().get_setting("output_dir") or os.environ.get("MDNOTES_NOTES_DIR")
                or str(DEFAULT_NOTES))


def _index() -> NoteIndex:
    return NoteIndex(INDEX_PATH)


def _drive_or_none():
    """Return a Drive service if a valid token exists, else None (never launches OAuth)."""
    from google.auth.transport.requests import Request as GReq
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from mdnotes.auth import SCOPES, TOKEN_PATH
    if not TOKEN_PATH.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(GReq())
            # persist so we don't refresh again on every request
            try:
                from mdnotes.fsutil import atomic_write_text
                atomic_write_text(TOKEN_PATH, creds.to_json(), mode=0o600)
            except OSError:
                pass
        if not creds.valid:
            return None
        return build("drive", "v3", credentials=creds)
    except Exception:
        return None


# ---------- app state ----------
@app.get("/api/status")
def api_status(_=Depends(require_auth)):
    try:
        courses = _index().courses()
    except Exception:
        courses = []
    return {
        "authed": _drive_or_none() is not None,
        "auth_running": _auth["running"],
        "auth_error": _auth["error"],
        "folder_name": _folder_name(),
        "folder_id": _folder_id(),
        "folder_configured": bool(_folder_id()),
        "output_dir": str(_output_dir()),
        "has_anthropic_key": bool(anthropic_key()),
        "has_voyage_key": bool(voyage_key()),
        "courses": courses,
        "sync": _sync,
    }


# ---------- google auth ----------
@app.post("/api/auth/login")
def api_login(_=Depends(require_auth), __=Depends(block_cross_site)):
    if _auth["running"]:
        raise HTTPException(status_code=409, detail="auth already in progress")
    _auth.update(running=True, error=None)  # reserve synchronously to close the double-start race

    def job():
        try:
            from mdnotes.auth import get_drive_service
            get_drive_service()  # opens a browser locally and stores the token
        except Exception as e:
            _auth["error"] = str(e)
        finally:
            _auth["running"] = False

    threading.Thread(target=job, daemon=True).start()
    return {"started": True}


# ---------- notes folder (setup wizard) ----------
@app.get("/api/drive/children")
def api_drive_children(parent: str = "root", _=Depends(require_auth)):
    svc = _drive_or_none()
    if svc is None:
        raise HTTPException(status_code=409, detail="not connected to Google Drive")
    return {"parent": parent, "folders": list_folder_children(svc, parent)}


# ---------- folder sync selection ----------
@app.get("/api/folders")
def api_folders(_=Depends(require_auth)):
    svc = _drive_or_none()
    if svc is None:
        raise HTTPException(status_code=409, detail="not connected to Google Drive")
    root_id = _folder_id()
    if not root_id:
        raise HTTPException(status_code=409, detail="choose your notes folder in Setup first")
    try:
        folders = walk_folders(svc, root_id)
    except Exception as e:
        print(f"walk_folders failed: {e}")
        raise HTTPException(status_code=502, detail="failed to list Drive folders")
    prefs = _prefs()
    for f in folders:
        choice = prefs.get(f["id"])
        f["choice"] = {YES: "sync", NO: "ignore"}.get(choice, "default")
    return {"root": _folder_name(), "folders": folders}


@app.post("/api/folders")
def api_set_folder(body: dict = Body(...), _=Depends(require_auth), __=Depends(block_cross_site)):
    folder_id = body.get("folder_id")
    choice = body.get("choice")
    name = body.get("name", "")
    if not folder_id or choice not in ("sync", "ignore", "default"):
        raise HTTPException(status_code=400, detail="folder_id and choice(sync|ignore|default) required")
    prefs = _prefs()
    if choice == "default":
        prefs.clear(folder_id)
    else:
        prefs.set(folder_id, YES if choice == "sync" else NO, name=name)
    return {"folder_id": folder_id, "choice": choice}


@app.post("/api/settings")
def api_settings(body: dict = Body(...), _=Depends(require_auth), __=Depends(block_cross_site)):
    prefs = _prefs()
    for key in ("folder_name", "folder_id", "output_dir"):
        if body.get(key):
            prefs.set_setting(key, body[key])
    return {"folder_name": _folder_name(), "folder_id": _folder_id(),
            "output_dir": str(_output_dir())}


# ---------- sync ----------
@app.post("/api/sync")
def api_sync(_=Depends(require_auth), __=Depends(block_cross_site)):
    if _sync["running"]:
        raise HTTPException(status_code=409, detail="sync already running")
    # reserve synchronously (before starting the thread) so two fast POSTs can't both pass
    _sync.update(running=True, started=datetime.now(timezone.utc).isoformat(),
                 result=None, error=None, stopping=False,
                 progress={"file": None, "page": 0, "pages": 0, "done": 0})

    def job():
        done = {"n": 0}

        def cb(ev):
            if ev.get("type") == "done":
                done["n"] += 1
            prev = _sync.get("progress") or {}
            _sync["progress"] = {
                "file": ev.get("path") or ev.get("name") or prev.get("file"),
                "page": ev.get("page", prev.get("page", 0)),
                "pages": ev.get("pages", prev.get("pages", 0)),
                "done": done["n"],
            }

        try:
            svc = _drive_or_none()
            if svc is None:
                raise RuntimeError("not connected to Google Drive")
            if not _folder_id():
                raise RuntimeError("choose your notes folder in Setup first")
            res = run_pipeline(
                service=svc, output_dir=_output_dir(), folder_name=_folder_name() or "notes",
                root_id=_folder_id(), cache_path=DEFAULT_CACHE, dpi=200, index_path=INDEX_PATH,
                interactive=False, default_choice=NO,
                progress=cb, should_stop=lambda: _sync["stopping"],
            )
            _sync["result"] = {"processed": res.processed, "skipped": res.skipped,
                               "errors": res.errors, "stopped": _sync["stopping"]}
        except Exception as e:
            _sync["error"] = str(e)
        finally:
            _sync["running"] = False

    threading.Thread(target=job, daemon=True).start()
    return {"started": True}


@app.post("/api/sync/stop")
def api_sync_stop(_=Depends(require_auth), __=Depends(block_cross_site)):
    if _sync["running"]:
        _sync["stopping"] = True
    return {"stopping": _sync["running"]}


@app.get("/api/sync/status")
def api_sync_status(_=Depends(require_auth)):
    return _sync


# ---------- search / read ----------
@app.get("/api/courses")
def api_courses(_=Depends(require_auth)):
    return {"courses": _index().courses()}


@app.get("/api/notes")
def api_notes(_=Depends(require_auth)):
    return {"notes": _index().list_notes()}


@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1, max_length=500),
               k: int = Query(15, ge=1, le=100),
               course: str | None = None, _=Depends(require_auth)):
    hits = run_search(_index(), q, k=k, course=course or None)
    return {"query": q, "course": course, "results": [h.__dict__ for h in hits]}


@app.get("/api/note/{note_id:path}")
def api_note(note_id: str, _=Depends(require_auth)):
    pages = _index().note_markdown(note_id)
    if not pages:
        raise HTTPException(status_code=404, detail="note not found")
    return {"note_id": note_id, "pages": pages}


@app.api_route("/api/pdf/{note_id:path}", methods=["GET", "HEAD"])
def api_pdf(note_id: str, _=Depends(require_auth)):
    md = _index().note_path(note_id)
    if md:
        pdf = Path(md).with_suffix(".pdf")
        if pdf.exists():
            # no-cache: a re-sync can replace this PDF, so the reader must revalidate
            return FileResponse(str(pdf), media_type="application/pdf",
                                headers={"Cache-Control": "private, no-cache"})
    raise HTTPException(status_code=404, detail="pdf not available")


_dist = Path(__file__).parent.parent.parent / "web" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")

    _dist_root = _dist.resolve()

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        # API routes are registered above and match first; everything else is the SPA
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        f = (_dist / full_path).resolve()
        # never serve outside dist (guards path traversal like ../../etc/passwd)
        if full_path and f.is_file() and f.is_relative_to(_dist_root):
            return FileResponse(str(f))
        return FileResponse(str(_dist_root / "index.html"))
