from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess
import pytest
from mdnotes.rasterize import rasterize_pdf, RasterizeError


def test_rasterize_returns_sorted_pages(tmp_path):
    """Given pdftoppm produces 3 JPEG files, we get 3 (num, bytes) tuples in order."""
    fake_pages = []
    for i in [1, 2, 3]:
        p = tmp_path / f"page-{i:03}.jpg"
        p.write_bytes(b"fakeimage" + bytes([i]))
        fake_pages.append(p)

    with patch("mdnotes.rasterize.subprocess.run") as mock_run, \
         patch("mdnotes.rasterize.tempfile.mkdtemp", return_value=str(tmp_path)):
        mock_run.return_value = MagicMock(returncode=0)
        pages = rasterize_pdf(Path("some.pdf"), dpi=150)

    assert len(pages) == 3
    assert pages[0][0] == 1
    assert pages[1][0] == 2
    assert pages[2][0] == 3


def test_rasterize_raises_on_pdftoppm_failure(tmp_path):
    with patch("mdnotes.rasterize.subprocess.run") as mock_run, \
         patch("mdnotes.rasterize.tempfile.mkdtemp", return_value=str(tmp_path)):
        mock_run.side_effect = subprocess.CalledProcessError(1, "pdftoppm")
        with pytest.raises(RasterizeError):
            rasterize_pdf(Path("bad.pdf"))
