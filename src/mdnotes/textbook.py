import subprocess
from pathlib import Path

from mdnotes.rasterize import pdf_page_count


class TextExtractError(Exception):
    pass


def _pdftotext_page(pdf_path: Path, page_num: int) -> str:
    """Extract the embedded text layer of a single page (1-indexed) via poppler."""
    try:
        out = subprocess.run(
            ["pdftotext", "-f", str(page_num), "-l", str(page_num), "-layout", str(pdf_path), "-"],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        raise TextExtractError(f"pdftotext failed for {pdf_path} page {page_num}: {e}") from e
    return out.stdout.strip()


def extract_pdf_pages(pdf_path: Path) -> list[dict]:
    """Return [{page_num, total, markdown}, ...] from a printed PDF's text layer."""
    total = pdf_page_count(pdf_path)
    pages = []
    for i in range(1, total + 1):
        text = _pdftotext_page(pdf_path, i)
        if text:
            pages.append({"page_num": i, "total": total, "markdown": text})
    return pages
