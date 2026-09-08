import os
import threading
import time

import voyageai

# current-gen lite models: same price as 3.5/2.5 lite but 200M free tokens each
EMBED_MODEL = "voyage-4-lite"
RERANK_MODEL = "rerank-3-lite"
EMBED_DIM = 1024

# set VOYAGE_MIN_INTERVAL (seconds between API calls) to stay under free-tier 3 RPM
_MIN_INTERVAL = float(os.environ.get("VOYAGE_MIN_INTERVAL", "0"))
_last_call = [0.0]
_throttle_lock = threading.Lock()


def _throttle():
    if _MIN_INTERVAL <= 0:
        return
    with _throttle_lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()


def _client(client):
    return client if client is not None else voyageai.Client()


def embed_documents(texts: list[str], client=None) -> list[list[float]]:
    """Embed a batch of note/textbook pages (document input type)."""
    if not texts:
        return []
    vo = _client(client)
    _throttle()
    return vo.embed(
        texts, model=EMBED_MODEL, input_type="document", output_dimension=EMBED_DIM
    ).embeddings


def embed_query(text: str, client=None) -> list[float]:
    """Embed a search query (query input type)."""
    vo = _client(client)
    _throttle()
    return vo.embed(
        [text], model=EMBED_MODEL, input_type="query", output_dimension=EMBED_DIM
    ).embeddings[0]


def rerank(query: str, documents: list[str], client=None, top_k=None) -> list[tuple[int, float]]:
    """Rerank documents against the query. Returns (original_index, score) sorted best-first."""
    if not documents:
        return []
    vo = _client(client)
    _throttle()
    res = vo.rerank(query, documents, model=RERANK_MODEL, top_k=top_k)
    return [(r.index, r.relevance_score) for r in res.results]
