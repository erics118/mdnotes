import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from mdnotes.index import DEFAULT_INDEX, NoteIndex
from mdnotes.search import search as run_search

INDEX_PATH = Path(os.environ.get("MDNOTES_INDEX", str(DEFAULT_INDEX)))
PASSWORD = os.environ.get("MDNOTES_PASSWORD")

app = FastAPI(title="mdnotes")
security = HTTPBasic(auto_error=False)


def require_auth(creds: HTTPBasicCredentials | None = Depends(security)):
    if PASSWORD is None:
        return
    if creds is None or not secrets.compare_digest(creds.password, PASSWORD):
        raise HTTPException(status_code=401, detail="unauthorized",
                            headers={"WWW-Authenticate": "Basic"})


def _index() -> NoteIndex:
    return NoteIndex(INDEX_PATH)


@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1), k: int = 10, _=Depends(require_auth)):
    hits = run_search(_index(), q, k=k)
    return {"query": q, "results": [h.__dict__ for h in hits]}


@app.get("/api/notes")
def api_notes(_=Depends(require_auth)):
    return {"notes": _index().list_notes()}


@app.get("/api/note/{note_id:path}")
def api_note(note_id: str, _=Depends(require_auth)):
    pages = _index().note_markdown(note_id)
    if not pages:
        raise HTTPException(status_code=404, detail="note not found")
    return {"note_id": note_id, "pages": pages}


_web = Path(__file__).parent.parent.parent / "web" / "dist"
if _web.exists():
    app.mount("/", StaticFiles(directory=str(_web), html=True), name="web")
