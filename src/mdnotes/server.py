import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from mdnotes.config import anthropic_key, voyage_key
from mdnotes.drive import find_goodnotes_folder_id, walk_folders
from mdnotes.index import DEFAULT_INDEX, NoteIndex
from mdnotes.pipeline import DEFAULT_CACHE, run_pipeline
from mdnotes.prefs import NO, SyncPrefs, YES
from mdnotes.search import search as run_search

INDEX_PATH = Path(os.environ.get("MDNOTES_INDEX", str(DEFAULT_INDEX)))
PASSWORD = os.environ.get("MDNOTES_PASSWORD")

app = FastAPI(title="mdnotes")
security = HTTPBasic(auto_error=False)

# background job state (single-user app)
_sync = {"running": False, "started": None, "result": None, "error": None}
_auth = {"running": False, "error": None}


def require_auth(request: Request, creds: HTTPBasicCredentials | None = Depends(security)):
    if PASSWORD is None:
        return
    supplied = (creds.password if creds else None) or request.query_params.get("pw")
    if supplied is None or not secrets.compare_digest(supplied, PASSWORD):
        raise HTTPException(status_code=401, detail="unauthorized",
                            headers={"WWW-Authenticate": "Basic"})


def _prefs() -> SyncPrefs:
    return SyncPrefs()


def _folder_name() -> str:
    return _prefs().get_setting("folder_name") or os.environ.get("MDNOTES_FOLDER") or "GoodNotes"


def _output_dir() -> Path:
    return Path(_prefs().get_setting("output_dir") or os.environ.get("MDNOTES_NOTES_DIR")
                or str(Path.home() / "notes"))


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
        "output_dir": str(_output_dir()),
        "has_anthropic_key": bool(anthropic_key()),
        "has_voyage_key": bool(voyage_key()),
        "courses": courses,
        "sync": _sync,
    }


# ---------- google auth ----------
@app.post("/api/auth/login")
def api_login(_=Depends(require_auth)):
    if _auth["running"]:
        raise HTTPException(status_code=409, detail="auth already in progress")

    def job():
        _auth.update(running=True, error=None)
        try:
            from mdnotes.auth import get_drive_service
            get_drive_service()  # opens a browser locally and stores the token
        except Exception as e:
            _auth["error"] = str(e)
        finally:
            _auth["running"] = False

    threading.Thread(target=job, daemon=True).start()
    return {"started": True}


# ---------- folder sync selection ----------
@app.get("/api/folders")
def api_folders(_=Depends(require_auth)):
    svc = _drive_or_none()
    if svc is None:
        raise HTTPException(status_code=409, detail="not connected to Google Drive")
    try:
        root_id = find_goodnotes_folder_id(svc, folder_name=_folder_name())
        folders = walk_folders(svc, root_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    prefs = _prefs()
    for f in folders:
        choice = prefs.get(f["id"])
        f["choice"] = {YES: "sync", NO: "ignore"}.get(choice, "default")
    return {"root": _folder_name(), "folders": folders}


@app.post("/api/folders")
def api_set_folder(body: dict = Body(...), _=Depends(require_auth)):
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
def api_settings(body: dict = Body(...), _=Depends(require_auth)):
    prefs = _prefs()
    for key in ("folder_name", "output_dir"):
        if body.get(key):
            prefs.set_setting(key, body[key])
    return {"folder_name": _folder_name(), "output_dir": str(_output_dir())}


# ---------- sync ----------
@app.post("/api/sync")
def api_sync(_=Depends(require_auth)):
    if _sync["running"]:
        raise HTTPException(status_code=409, detail="sync already running")

    def job():
        _sync.update(running=True, started=datetime.now(timezone.utc).isoformat(),
                     result=None, error=None)
        try:
            svc = _drive_or_none()
            if svc is None:
                raise RuntimeError("not connected to Google Drive")
            res = run_pipeline(
                service=svc, output_dir=_output_dir(), folder_name=_folder_name(),
                cache_path=DEFAULT_CACHE, dpi=200, index_path=INDEX_PATH,
                interactive=False, default_choice=NO,
            )
            _sync["result"] = {"processed": res.processed, "skipped": res.skipped,
                               "errors": res.errors}
        except Exception as e:
            _sync["error"] = str(e)
        finally:
            _sync["running"] = False

    threading.Thread(target=job, daemon=True).start()
    return {"started": True}


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
def api_search(q: str = Query(..., min_length=1), k: int = 15,
               course: str | None = None, _=Depends(require_auth)):
    hits = run_search(_index(), q, k=k, course=course or None)
    return {"query": q, "course": course, "results": [h.__dict__ for h in hits]}


@app.get("/api/note/{note_id:path}")
def api_note(note_id: str, _=Depends(require_auth)):
    pages = _index().note_markdown(note_id)
    if not pages:
        raise HTTPException(status_code=404, detail="note not found")
    return {"note_id": note_id, "pages": pages}


@app.get("/api/pdf/{note_id:path}")
def api_pdf(note_id: str, _=Depends(require_auth)):
    md = _index().note_path(note_id)
    if md:
        pdf = Path(md).with_suffix(".pdf")
        if pdf.exists():
            return FileResponse(str(pdf), media_type="application/pdf",
                                headers={"Cache-Control": "private, max-age=86400"})
    raise HTTPException(status_code=404, detail="pdf not available")


_web = Path(__file__).parent.parent.parent / "web"
if _web.exists():
    app.mount("/", StaticFiles(directory=str(_web), html=True), name="web")
