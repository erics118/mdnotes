import re

HANDWRITTEN = "handwritten"
TEXTBOOK = "textbook"

# a page block: "<!-- page N/total -->\n<markdown>", blocks joined by "\n\n---\n\n"
# the lookahead requires the separator to be followed by a page marker, so a bare
# "---" inside transcribed content does not split a page
_PAGE_RE = re.compile(
    r"<!-- page (\d+)/(\d+) -->\n(.*?)(?=\n\n---\n\n<!-- page |\Z)",
    re.DOTALL,
)

# a hidden, index-only enrichment block trailing a page's markdown (never displayed);
# feeds the embedding + FTS index to bridge terse math notation and plain-language queries
_CONTEXT_RE = re.compile(r"\n\n<!-- mdnotes:context\n(.*?)\n-->\s*$", re.DOTALL)


def _sanitize_context(s: str) -> str:
    """Keep the context body from breaking page/comment parsing."""
    s = s.replace("-->", "--").strip()
    return s.replace("\n---\n", "\n- - -\n")


def split_context(page_content: str) -> tuple[str, str]:
    """Split a page's body into (displayed markdown, hidden search context)."""
    m = _CONTEXT_RE.search(page_content)
    if not m:
        return page_content.strip(), ""
    return page_content[:m.start()].strip(), m.group(1).strip()


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split leading YAML frontmatter (simple key: value lines) from the body."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    meta = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta, text[end + 5:].lstrip("\n")


def build_frontmatter(meta: dict) -> str:
    body = "\n".join(f"{k}: {v}" for k, v in meta.items())
    return f"---\n{body}\n---\n"


def build_note(meta: dict, page_blocks: list[str]) -> str:
    """Assemble a full note file: frontmatter then page blocks."""
    return build_frontmatter(meta) + "\n" + "\n\n---\n\n".join(page_blocks)


def page_block(page_num: int, total: int, markdown: str, search_context: str = "") -> str:
    block = f"<!-- page {page_num}/{total} -->\n{markdown}"
    ctx = _sanitize_context(search_context) if search_context else ""
    if ctx:
        block += f"\n\n<!-- mdnotes:context\n{ctx}\n-->"
    return block


def parse_pages(text: str) -> list[dict]:
    """Return [{page_num, total, markdown, search_context}, ...] from a note file's body."""
    _, body = parse_frontmatter(text)
    pages = []
    for m in _PAGE_RE.findall(body):
        markdown, context = split_context(m[2])
        pages.append({"page_num": int(m[0]), "total": int(m[1]),
                      "markdown": markdown, "search_context": context})
    return pages


def source_type(text: str) -> str:
    meta, _ = parse_frontmatter(text)
    return meta.get("source_type", HANDWRITTEN)
