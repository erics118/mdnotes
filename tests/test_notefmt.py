from mdnotes.notefmt import (
    HANDWRITTEN, TEXTBOOK, build_note, page_block, parse_frontmatter, parse_pages, source_type,
)


def test_frontmatter_roundtrip():
    text = build_note(
        {"source_type": TEXTBOOK, "synced": "2026-01-01T00:00:00Z"},
        [page_block(1, 2, "hello $x$"), page_block(2, 2, "world")],
    )
    meta, body = parse_frontmatter(text)
    assert meta["source_type"] == "textbook"
    assert meta["synced"] == "2026-01-01T00:00:00Z"
    assert body.startswith("<!-- page 1/2 -->")


def test_parse_pages_and_source_type():
    text = build_note({"source_type": HANDWRITTEN},
                      [page_block(1, 3, "a"), page_block(2, 3, "b"), page_block(3, 3, "c")])
    pages = parse_pages(text)
    assert [p["page_num"] for p in pages] == [1, 2, 3]
    assert pages[1]["markdown"] == "b"
    assert source_type(text) == HANDWRITTEN


def test_source_type_defaults_handwritten_without_frontmatter():
    assert source_type("no frontmatter here") == HANDWRITTEN


def test_bare_dash_in_content_does_not_split_page():
    # a lone "---" inside a page must not be read as a page separator
    text = build_note({"source_type": HANDWRITTEN}, [page_block(1, 1, "line\n\n---\n\nmore")])
    pages = parse_pages(text)
    assert len(pages) == 1
    assert "more" in pages[0]["markdown"]
