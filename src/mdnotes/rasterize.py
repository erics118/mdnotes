import hashlib
import subprocess
import tempfile
import shutil
from pathlib import Path
from pypdf import PdfReader


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


def rasterize_pdf(pdf_path: Path, dpi: int = 150) -> list[tuple[int, bytes]]:
    """
    Rasterize all pages of a PDF to JPEG images.
    Returns a sorted list of (page_number, image_bytes) tuples.
    Requires poppler's pdftoppm to be installed.
    """
    tmp_dir = Path(tempfile.mkdtemp())
    prefix = tmp_dir / "page"
    try:
        subprocess.run(
            ["pdftoppm", "-jpeg", "-r", str(dpi), str(pdf_path), str(prefix)],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RasterizeError(f"pdftoppm failed for {pdf_path}: {e}") from e

    pages = sorted(tmp_dir.glob("page-*.jpg"))
    result = []
    for page_file in pages:
        # filename pattern: page-001.jpg → page number 1
        num = int(page_file.stem.split("-")[-1])
        result.append((num, page_file.read_bytes()))

    shutil.rmtree(tmp_dir)
    return result
