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
    content_obj = page.get("/Contents")
    if content_obj is None:
        data = b""
    else:
        obj = content_obj.get_object()
        data = obj.get_data() if hasattr(obj, "get_data") else str(obj).encode()
    return hashlib.sha256(data).hexdigest()


def rasterize_page(pdf_path: Path, page_num: int, dpi: int = 150) -> bytes:
    """
    Rasterize a single page (1-indexed) to JPEG bytes.
    Uses pdftoppm -f/-l flags to render only that page.
    """
    tmp_dir = Path(tempfile.mkdtemp())
    prefix = tmp_dir / "page"
    try:
        subprocess.run(
            ["pdftoppm", "-jpeg", "-r", str(dpi),
             "-f", str(page_num), "-l", str(page_num),
             str(pdf_path), str(prefix)],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RasterizeError(f"pdftoppm failed for {pdf_path} page {page_num}: {e}") from e

    pages = list(tmp_dir.glob("page-*.jpg"))
    if not pages:
        shutil.rmtree(tmp_dir)
        raise RasterizeError(f"pdftoppm produced no output for {pdf_path} page {page_num}")

    data = pages[0].read_bytes()
    shutil.rmtree(tmp_dir)
    return data
