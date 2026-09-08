from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import mdnotes.server as server
from mdnotes.search import Hit


def _hit():
    return Hit(note_id="n1", title="lec", page_num=3, path="/x/lec.md",
               source_type="handwritten", score=0.9, snippet="injective ...")


def test_search_endpoint():
    client = TestClient(server.app)
    with patch.object(server, "PASSWORD", None), \
         patch.object(server, "_index", return_value=MagicMock()), \
         patch.object(server, "run_search", return_value=[_hit()]) as rs:
        r = client.get("/api/search", params={"q": "injective"})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "injective"
    assert body["results"][0]["title"] == "lec"
    assert body["results"][0]["page_num"] == 3
    rs.assert_called_once()


def test_search_requires_auth_when_password_set():
    client = TestClient(server.app)
    with patch.object(server, "PASSWORD", "secret"), \
         patch.object(server, "_index", return_value=MagicMock()), \
         patch.object(server, "run_search", return_value=[]):
        unauth = client.get("/api/search", params={"q": "x"})
        ok = client.get("/api/search", params={"q": "x"}, auth=("", "secret"))
    assert unauth.status_code == 401
    assert ok.status_code == 200


def test_note_404():
    client = TestClient(server.app)
    with patch.object(server, "PASSWORD", None), \
         patch.object(server, "_index") as idx:
        idx.return_value.note_markdown.return_value = []
        r = client.get("/api/note/missing.md")
    assert r.status_code == 404


def test_courses_endpoint():
    client = TestClient(server.app)
    with patch.object(server, "PASSWORD", None), patch.object(server, "_index") as idx:
        idx.return_value.courses.return_value = ["CS 2800", "MATH 3360"]
        r = client.get("/api/courses")
    assert r.status_code == 200
    assert r.json()["courses"] == ["CS 2800", "MATH 3360"]


def test_pdf_served_when_present(tmp_path):
    md = tmp_path / "n.md"
    (tmp_path / "n.pdf").write_bytes(b"%PDF-1.7 fake")
    client = TestClient(server.app)
    with patch.object(server, "PASSWORD", None), patch.object(server, "_index") as idx:
        idx.return_value.note_path.return_value = str(md)
        r = client.get("/api/pdf/n.md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")


def test_pdf_404_when_missing(tmp_path):
    client = TestClient(server.app)
    with patch.object(server, "PASSWORD", None), patch.object(server, "_index") as idx:
        idx.return_value.note_path.return_value = str(tmp_path / "missing.md")
        r = client.get("/api/pdf/missing.md")
    assert r.status_code == 404


def test_search_passes_course():
    client = TestClient(server.app)
    with patch.object(server, "PASSWORD", None), \
         patch.object(server, "_index", return_value=MagicMock()), \
         patch.object(server, "run_search", return_value=[]) as rs:
        client.get("/api/search", params={"q": "x", "course": "MATH 3360"})
    assert rs.call_args.kwargs["course"] == "MATH 3360"
