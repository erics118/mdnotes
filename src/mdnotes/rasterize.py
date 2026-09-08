import hashlib
import logging
import subprocess
import tempfile
import shutil
from pathlib import Path
from pypdf import PdfReader

# pypdf emits warnings for minor PDF corruption common in GoodNotes exports
logging.getLogger("pypdf").setLevel(logging.ERROR)


class RasterizeError(Exception):
    pass


def pdf_page_count(pdf_path: Path) -> int:
    """Return the number of pages in a PDF without rasterizing."""
    return len(PdfReader(pdf_path).pages)


def pdf_page_hash(pdf_path: Path, page_num: int) -> str:
    """
    Return a SHA-256 hash of a single page's raw content stream (1-indexed).
    Stable across re-downloads of the same PDF — does not depend on rasterization.
    """
    reader = PdfReader(pdf_path)
    page = reader.pages[page_num - 1]
    # get_contents() merges an array of content streams into one and returns decoded
    # bytes; hashing str(obj) instead embeds a per-process id() and is unstable.
    content = page.get_contents()
    data = content.get_data() if content is not None else b""
    return hashlib.sha256(data).hexdigest()


def rasterize_page(pdf_path: Path, page_num: int, dpi: int = 200) -> bytes:
    """
    Rasterize a single page (1-indexed) to JPEG bytes.
    Uses pdftoppm -f/-l flags to render only that page.
    """
    tmp_dir = Path(tempfile.mkdtemp())
    prefix = tmp_dir / "page"
    try:
        try:
            subprocess.run(
                ["pdftoppm", "-jpeg", "-r", str(dpi),
                 "-f", str(page_num), "-l", str(page_num),
                 str(pdf_path), str(prefix)],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError as e:
            raise RasterizeError("pdftoppm (poppler) is not installed") from e
        except subprocess.CalledProcessError as e:
            raise RasterizeError(f"pdftoppm failed for {pdf_path} page {page_num}: {e}") from e

        pages = list(tmp_dir.glob("page-*.jpg"))
        if not pages:
            raise RasterizeError(f"pdftoppm produced no output for {pdf_path} page {page_num}")
        return pages[0].read_bytes()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
