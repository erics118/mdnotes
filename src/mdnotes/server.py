import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from mdnotes.index import DEFAULT_INDEX, NoteIndex
from mdnotes.search import search as run_search

INDEX_PATH = Path(os.environ.get("MDNOTES_INDEX", str(DEFAULT_INDEX)))
PASSWORD = os.environ.get("MDNOTES_PASSWORD")

app = FastAPI(title="mdnotes")
security = HTTPBasic(auto_error=False)


def require_auth(request: Request, creds: HTTPBasicCredentials | None = Depends(security)):
    # accept the password via Basic auth (fetch) or a ?pw= query (so the PDF iframe can auth)
    if PASSWORD is None:
        return
    supplied = (creds.password if creds else None) or request.query_params.get("pw")
    if supplied is None or not secrets.compare_digest(supplied, PASSWORD):
        raise HTTPException(status_code=401, detail="unauthorized",
                            headers={"WWW-Authenticate": "Basic"})


def _index() -> NoteIndex:
    return NoteIndex(INDEX_PATH)


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
