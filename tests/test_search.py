from mdnotes.index import NoteIndex
from mdnotes.search import rrf_fuse, search
from test_index import FakeVoyage


def test_rrf_fuse_rewards_agreement():
    # id 2 appears high in both lists -> should win
    vec = [1, 2, 3]
    fts = [4, 2, 5]
    fused = rrf_fuse(vec, fts)
    assert fused[0] == 2
    assert set(fused) == {1, 2, 3, 4, 5}


def test_rrf_fuse_empty():
    assert rrf_fuse([], []) == []


def test_search_end_to_end(tmp_path):
    fake = FakeVoyage()
    idx = NoteIndex(path=tmp_path / "index.db", embed_client=fake)
    idx.upsert_note("math/lec.md", "lec", [
        {"page_num": 1, "total": 2, "markdown": "eigenvalues and eigenvectors of a matrix"},
        {"page_num": 2, "total": 2, "markdown": "a recipe for chocolate cake"},
    ])

    hits = search(idx, "eigenvalues", k=2, embed_client=fake, rerank_client=fake)

    assert hits
    assert hits[0].title == "lec"
    assert hits[0].page_num == 1
    assert hits[0].source_type == "handwritten"
    assert "eigenvalues" in hits[0].snippet


def test_search_scoped_to_course(tmp_path):
    fake = FakeVoyage()
    idx = NoteIndex(path=tmp_path / "index.db", embed_client=fake)
    idx.upsert_note("MATH 3360/lec.md", "lec", [
        {"page_num": 1, "total": 1, "markdown": "group homomorphism definition"}])
    idx.upsert_note("CS 2800/lec.md", "lec", [
        {"page_num": 1, "total": 1, "markdown": "group of vertices in a graph"}])

    hits = search(idx, "group", k=5, course="MATH 3360", embed_client=fake, rerank_client=fake)
    assert hits
    assert all(h.note_id.startswith("MATH 3360/") for h in hits)


def test_search_no_results_empty_index(tmp_path):
    fake = FakeVoyage()
    idx = NoteIndex(path=tmp_path / "index.db", embed_client=fake)
    assert search(idx, "anything", embed_client=fake, rerank_client=fake) == []
