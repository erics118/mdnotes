import subprocess
from pathlib import Path

from mdnotes.rasterize import pdf_page_count


class TextExtractError(Exception):
    pass


def _pdftotext_all(pdf_path: Path) -> list[str]:
    """Extract the text layer of every page in one poppler call (form-feed delimited)."""
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            check=True, capture_output=True, text=True,
        )
    except FileNotFoundError as e:
        raise TextExtractError("pdftotext (poppler) is not installed") from e
    except subprocess.CalledProcessError as e:
        raise TextExtractError(f"pdftotext failed for {pdf_path}: {e}") from e
    # pdftotext separates pages with a form feed; a trailing one yields an empty tail
    return out.stdout.split("\f")


def extract_pdf_pages(pdf_path: Path) -> list[dict]:
    """Return [{page_num, total, markdown}, ...] from a printed PDF's text layer."""
    total = pdf_page_count(pdf_path)
    chunks = _pdftotext_all(pdf_path)
    pages = []
    for i in range(total):
        text = chunks[i].strip() if i < len(chunks) else ""
        if text:
            pages.append({"page_num": i + 1, "total": total, "markdown": text})
    return pages
