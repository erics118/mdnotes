from types import SimpleNamespace
from unittest.mock import patch

from mdnotes.index import detect_source_type, HANDWRITTEN, TEXTBOOK
from mdnotes.textbook import extract_pdf_pages


def test_extract_pdf_pages(tmp_path):
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.7 fake")

    with patch("mdnotes.textbook.pdf_page_count", return_value=3), \
         patch("mdnotes.textbook.subprocess.run") as run:
        run.side_effect = [
            SimpleNamespace(stdout="page one text"),
            SimpleNamespace(stdout="   "),          # blank page dropped
            SimpleNamespace(stdout="page three text"),
        ]
        pages = extract_pdf_pages(pdf)

    assert [p["page_num"] for p in pages] == [1, 3]
    assert pages[0]["total"] == 3
    assert pages[0]["markdown"] == "page one text"


def test_detect_source_type():
    assert detect_source_type("<!-- mdnotes: source: textbook -->\n...") == TEXTBOOK
    assert detect_source_type("<!-- mdnotes: synced: x -->\n...") == HANDWRITTEN
