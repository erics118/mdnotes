from unittest.mock import MagicMock, patch

import pytest
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


def test_pdf_head_probe_ok(tmp_path):
    # the reader probes with HEAD before embedding the PDF; must not 405
    md = tmp_path / "n.md"
    (tmp_path / "n.pdf").write_bytes(b"%PDF-1.7 fake")
    client = TestClient(server.app)
    with patch.object(server, "PASSWORD", None), patch.object(server, "_index") as idx:
        idx.return_value.note_path.return_value = str(md)
        r = client.head("/api/pdf/n.md")
    assert r.status_code == 200


def test_pdf_404_when_missing(tmp_path):
    client = TestClient(server.app)
    with patch.object(server, "PASSWORD", None), patch.object(server, "_index") as idx:
        idx.return_value.note_path.return_value = str(tmp_path / "missing.md")
        r = client.get("/api/pdf/missing.md")
    assert r.status_code == 404


def test_status_shape():
    client = TestClient(server.app)
    with patch.object(server, "PASSWORD", None), \
         patch.object(server, "_drive_or_none", return_value=None), \
         patch.object(server, "_index") as idx:
        idx.return_value.courses.return_value = []
        r = client.get("/api/status")
    assert r.status_code == 200
    b = r.json()
    assert b["authed"] is False
    assert "has_anthropic_key" in b and "has_voyage_key" in b
    assert b["sync"]["running"] is False


def test_folders_requires_drive():
    client = TestClient(server.app)
    with patch.object(server, "PASSWORD", None), patch.object(server, "_drive_or_none", return_value=None):
        r = client.get("/api/folders")
    assert r.status_code == 409


def test_folders_lists_with_choice():
    client = TestClient(server.app)
    prefs = MagicMock()
    prefs.get.side_effect = lambda fid: {"c1": "no"}.get(fid)  # CS 2800 ignored
    with patch.object(server, "PASSWORD", None), \
         patch.object(server, "_drive_or_none", return_value=MagicMock()), \
         patch.object(server, "_folder_id", return_value="rootid"), \
         patch.object(server, "walk_folders", return_value=[
             {"id": "c1", "name": "CS 2800", "path": "CS 2800", "parent_id": None},
             {"id": "c2", "name": "MATH 3360", "path": "MATH 3360", "parent_id": None}]), \
         patch.object(server, "_prefs", return_value=prefs):
        r = client.get("/api/folders")
    assert r.status_code == 200
    by = {f["name"]: f["choice"] for f in r.json()["folders"]}
    assert by["CS 2800"] == "ignore" and by["MATH 3360"] == "default"


def test_folders_requires_folder_chosen():
    client = TestClient(server.app)
    with patch.object(server, "PASSWORD", None), \
         patch.object(server, "_drive_or_none", return_value=MagicMock()), \
         patch.object(server, "_folder_id", return_value=None):
        r = client.get("/api/folders")
    assert r.status_code == 409


def test_drive_children():
    client = TestClient(server.app)
    with patch.object(server, "PASSWORD", None), \
         patch.object(server, "_drive_or_none", return_value=MagicMock()), \
         patch.object(server, "list_folder_children", return_value=[{"id": "x", "name": "GoodNotes"}]):
        r = client.get("/api/drive/children", params={"parent": "root"})
    assert r.status_code == 200
    assert r.json()["folders"][0]["name"] == "GoodNotes"


def test_set_folder_pref():
    client = TestClient(server.app)
    prefs = MagicMock()
    with patch.object(server, "PASSWORD", None), patch.object(server, "_prefs", return_value=prefs):
        r = client.post("/api/folders", json={"folder_id": "c1", "name": "CS 2800", "choice": "sync"})
    assert r.status_code == 200
    prefs.set.assert_called_once()


def test_sync_stop_sets_flag():
    client = TestClient(server.app)
    server._sync["running"] = True
    server._sync["stopping"] = False
    try:
        with patch.object(server, "PASSWORD", None):
            r = client.post("/api/sync/stop")
        assert r.json()["stopping"] is True
        assert server._sync["stopping"] is True
    finally:
        server._sync["running"] = False
        server._sync["stopping"] = False


def test_sync_conflict_when_running():
    client = TestClient(server.app)
    server._sync["running"] = True
    try:
        with patch.object(server, "PASSWORD", None):
            r = client.post("/api/sync")
        assert r.status_code == 409
    finally:
        server._sync["running"] = False


def test_spa_blocks_path_traversal():
    if not server._dist.exists():
        pytest.skip("web/dist not built")
    client = TestClient(server.app)
    with patch.object(server, "PASSWORD", None):
        r = client.get("/%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd")
    # falls back to the SPA shell, never serves a file outside dist
    assert r.status_code == 200
    assert b"root:" not in r.content
    assert b'<div id="root">' in r.content


def test_search_passes_course():
    client = TestClient(server.app)
    with patch.object(server, "PASSWORD", None), \
         patch.object(server, "_index", return_value=MagicMock()), \
         patch.object(server, "run_search", return_value=[]) as rs:
        client.get("/api/search", params={"q": "x", "course": "MATH 3360"})
    assert rs.call_args.kwargs["course"] == "MATH 3360"
