import subprocess
import tempfile
import shutil
from pathlib import Path


class RasterizeError(Exception):
    pass


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
