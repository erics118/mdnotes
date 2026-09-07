import voyageai

EMBED_MODEL = "voyage-3.5-lite"
RERANK_MODEL = "rerank-2.5-lite"
EMBED_DIM = 1024


def _client(client):
    return client if client is not None else voyageai.Client()


def embed_documents(texts: list[str], client=None) -> list[list[float]]:
    """Embed a batch of note/textbook pages (document input type)."""
    if not texts:
        return []
    vo = _client(client)
    return vo.embed(
        texts, model=EMBED_MODEL, input_type="document", output_dimension=EMBED_DIM
    ).embeddings


def embed_query(text: str, client=None) -> list[float]:
    """Embed a search query (query input type)."""
    vo = _client(client)
    return vo.embed(
        [text], model=EMBED_MODEL, input_type="query", output_dimension=EMBED_DIM
    ).embeddings[0]


def rerank(query: str, documents: list[str], client=None, top_k=None) -> list[tuple[int, float]]:
    """Rerank documents against the query. Returns (original_index, score) sorted best-first."""
    if not documents:
        return []
    vo = _client(client)
    res = vo.rerank(query, documents, model=RERANK_MODEL, top_k=top_k)
    return [(r.index, r.relevance_score) for r in res.results]
