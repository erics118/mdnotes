from types import SimpleNamespace
from unittest.mock import patch

from mdnotes.notefmt import source_type as detect_source_type, HANDWRITTEN, TEXTBOOK
from mdnotes.textbook import extract_pdf_pages


def test_extract_pdf_pages(tmp_path):
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.7 fake")

    with patch("mdnotes.textbook.pdf_page_count", return_value=3), \
         patch("mdnotes.textbook.subprocess.run") as run:
        # one call, pages separated by form feed; blank middle page dropped
        run.return_value = SimpleNamespace(stdout="page one text\f   \fpage three text\f")
        pages = extract_pdf_pages(pdf)

    assert run.call_count == 1
    assert [p["page_num"] for p in pages] == [1, 3]
    assert pages[0]["total"] == 3
    assert pages[0]["markdown"] == "page one text"


def test_detect_source_type():
    assert detect_source_type("---\nsource_type: textbook\n---\n...") == TEXTBOOK
    assert detect_source_type("---\nsynced: x\n---\n...") == HANDWRITTEN
