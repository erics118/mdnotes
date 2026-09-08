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


def page_block(page_num: int, total: int, markdown: str) -> str:
    return f"<!-- page {page_num}/{total} -->\n{markdown}"


def parse_pages(text: str) -> list[dict]:
    """Return [{page_num, total, markdown}, ...] from a note file's body."""
    _, body = parse_frontmatter(text)
    return [
        {"page_num": int(m[0]), "total": int(m[1]), "markdown": m[2].strip()}
        for m in _PAGE_RE.findall(body)
    ]


def source_type(text: str) -> str:
    meta, _ = parse_frontmatter(text)
    return meta.get("source_type", HANDWRITTEN)
