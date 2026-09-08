from dataclasses import dataclass

from mdnotes.embed import embed_query, rerank


def rrf_fuse(*ranked_lists: list[int], k: int = 60) -> list[int]:
    """Reciprocal-rank fusion of several ranked id lists (best first)."""
    scores: dict[int, float] = {}
    for lst in ranked_lists:
        for rank, item in enumerate(lst):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda i: scores[i], reverse=True)


@dataclass
class Hit:
    note_id: str
    title: str
    page_num: int
    path: str | None
    source_type: str
    score: float
    snippet: str


def _snippet(markdown: str, n: int = 240) -> str:
    text = " ".join(markdown.split())
    return text[:n] + ("..." if len(text) > n else "")


def search(
    index,
    query: str,
    k: int = 10,
    course: str | None = None,
    embed_client=None,
    rerank_client=None,
    candidates: int = 40,
    fuse_top: int = 30,
) -> list[Hit]:
    """Hybrid search: vector KNN + FTS BM25, RRF-fused, then Voyage rerank.

    course: restrict results to notes under that top-level folder.
    """
    q_vec = embed_query(query, client=embed_client)
    # over-fetch when scoping to a course so the prefix filter still fills fuse_top
    limit = candidates if course is None else max(candidates, 1000)
    vec_ids = index.vec_candidates(q_vec, limit=limit)
    fts_ids = index.fts_candidates(query, limit=limit)
    if course:
        allowed = index.page_ids_under(course)
        vec_ids = [i for i in vec_ids if i in allowed]
        fts_ids = [i for i in fts_ids if i in allowed]
    fused = rrf_fuse(vec_ids, fts_ids)[:fuse_top]
    if not fused:
        return []

    pages = [p for p in (index.get_page(pid) for pid in fused) if p is not None]
    ranked = rerank(query, [p["markdown"] for p in pages], client=rerank_client, top_k=k)

    hits = []
    for idx, score in ranked:
        p = pages[idx]
        hits.append(Hit(
            note_id=p["note_id"],
            title=p["title"],
            page_num=p["page_num"],
            path=p["path"],
            source_type=p["source_type"],
            score=score,
            snippet=_snippet(p["markdown"]),
        ))
    return hits
