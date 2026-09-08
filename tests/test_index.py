import hashlib
from types import SimpleNamespace

from mdnotes.index import NoteIndex, content_hash
from mdnotes.notefmt import parse_pages


class FakeVoyage:
    """Deterministic stand-in for voyageai.Client used across index/search tests."""

    def __init__(self):
        self.embed_calls = 0
        self.embed_text_count = 0

    def embed(self, texts, model=None, input_type=None, output_dimension=None):
        self.embed_calls += 1
        self.embed_text_count += len(texts)
        return SimpleNamespace(embeddings=[self.vec(t) for t in texts])

    def rerank(self, query, documents, model=None, top_k=None):
        qset = set(query.lower().split())
        scored = [
            SimpleNamespace(index=i, relevance_score=float(len(qset & set(d.lower().split()))))
            for i, d in enumerate(documents)
        ]
        scored.sort(key=lambda r: r.relevance_score, reverse=True)
        return SimpleNamespace(results=scored[:top_k] if top_k else scored)

    @staticmethod
    def vec(text):
        h = hashlib.sha256(text.encode()).digest()
        base = [b / 255.0 for b in h]
        return (base * 32)[:1024]


def _index(tmp_path):
    return NoteIndex(path=tmp_path / "index.db", embed_client=FakeVoyage())


def _pages(*texts):
    return [{"page_num": i + 1, "total": len(texts), "markdown": t} for i, t in enumerate(texts)]


def test_upsert_creates_page_fts_and_vec_rows(tmp_path):
    idx = _index(tmp_path)
    idx.upsert_note("cs2800/lec01.md", "lec01", _pages("proof by induction", "pigeonhole principle"))

    assert idx.db.execute("select count(*) from pages").fetchone()[0] == 2
    assert idx.db.execute("select count(*) from vec_pages").fetchone()[0] == 2
    assert idx.db.execute("select count(*) from pages_fts").fetchone()[0] == 2
    assert idx.db.execute("select count(*) from notes").fetchone()[0] == 1


def test_reupsert_replaces_stale_pages(tmp_path):
    idx = _index(tmp_path)
    idx.upsert_note("n1", "n1", _pages("alpha", "beta", "gamma"))
    idx.upsert_note("n1", "n1", _pages("delta"))

    assert idx.db.execute("select count(*) from pages").fetchone()[0] == 1
    assert idx.db.execute("select count(*) from vec_pages").fetchone()[0] == 1
    assert idx.db.execute("select markdown from pages").fetchone()[0] == "delta"


def test_embedding_cache_prevents_reembedding(tmp_path):
    fake = FakeVoyage()
    idx = NoteIndex(path=tmp_path / "index.db", embed_client=fake)

    idx.upsert_note("n1", "n1", _pages("shared page", "unique one"))
    assert fake.embed_text_count == 2

    # re-index a note containing the same "shared page" content: only the new text embeds
    idx.upsert_note("n2", "n2", _pages("shared page", "brand new"))
    assert fake.embed_text_count == 3


def test_fts_and_vec_candidates_return_page_ids(tmp_path):
    idx = _index(tmp_path)
    idx.upsert_note("n1", "n1", _pages("eigenvalues of a matrix", "unrelated cooking recipe"))

    fts = idx.fts_candidates("eigenvalues", limit=10)
    assert len(fts) >= 1
    assert idx.get_page(fts[0])["markdown"].startswith("eigenvalues")

    vec = idx.vec_candidates(FakeVoyage.vec("eigenvalues of a matrix"), limit=10)
    assert len(vec) == 2


def test_parse_pages():
    text = (
        "---\nsynced: 2026-04-15T12:00:00.000000Z\n---\n\n"
        "<!-- page 1/2 -->\nfirst page $x^2$\n\n---\n\n"
        "<!-- page 2/2 -->\nsecond page"
    )
    pages = parse_pages(text)
    assert [p["page_num"] for p in pages] == [1, 2]
    assert pages[0]["markdown"] == "first page $x^2$"
    assert pages[1]["markdown"] == "second page"


def test_content_hash_matches_sha256():
    assert content_hash("hi") == hashlib.sha256(b"hi").hexdigest()
