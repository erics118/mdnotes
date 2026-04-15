# GoodNotes → Markdown Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI tool that downloads GoodNotes-synced PDFs from Google Drive, rasterizes each page, transcribes handwriting to Markdown via a cheap vision model, and saves `.md` files for LLM ingestion.

**Architecture:** A four-stage pipeline — `auth → download → rasterize → transcribe` — each stage encapsulated in its own module. Transcriptions are cached by page content hash so re-runs only process new or changed pages. A thin CLI wires the stages together.

**Tech Stack:** Python 3.11+, `google-api-python-client`, `google-auth-oauthlib`, `anthropic`, `poppler-utils` (system dep for `pdftoppm`), `click`, `pytest`, `pytest-mock`

---

## File Structure

```
mdnotes/
├── pyproject.toml               # deps, entry point
├── .gitignore
├── credentials/                 # gitignored — OAuth token lives here
│   └── .gitkeep
├── src/
│   └── mdnotes/
│       ├── __init__.py
│       ├── auth.py              # Google OAuth2 flow + token refresh
│       ├── drive.py             # list + download PDFs from Drive
│       ├── rasterize.py         # PDF → JPEG page images via pdftoppm
│       ├── transcribe.py        # page image → Markdown via Claude vision
│       ├── cache.py             # content-hash-based skip cache
│       ├── pipeline.py          # orchestrates all stages end-to-end
│       └── cli.py               # `mdnotes sync` CLI entry point
└── tests/
    ├── conftest.py              # shared fixtures
    ├── test_auth.py
    ├── test_drive.py
    ├── test_rasterize.py
    ├── test_transcribe.py
    ├── test_cache.py
    └── test_pipeline.py
```

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `credentials/.gitkeep`
- Create: `src/mdnotes/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "mdnotes"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.25",
    "google-api-python-client>=2.120",
    "google-auth-oauthlib>=1.2",
    "click>=8.1",
]

[project.scripts]
mdnotes = "mdnotes.cli:main"

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-mock>=3.12",
]

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Create `.gitignore`**

```
credentials/*.json
credentials/token.json
__pycache__/
*.pyc
.env
dist/
*.egg-info/
/tmp/
```

- [ ] **Step 3: Create `credentials/.gitkeep` and `src/mdnotes/__init__.py`**

```bash
mkdir -p credentials src/mdnotes tests
touch credentials/.gitkeep src/mdnotes/__init__.py
```

- [ ] **Step 4: Create `tests/conftest.py`**

```python
# tests/conftest.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir(tmp_path):
    return tmp_path


@pytest.fixture
def mock_drive_service():
    svc = MagicMock()
    return svc
```

- [ ] **Step 5: Install in editable mode**

```bash
pip install -e ".[dev]"
```

Expected: installs without error, `mdnotes --help` prints usage.

- [ ] **Step 6: Verify tests can be collected**

```bash
pytest --collect-only
```

Expected: `no tests ran` (zero collected, no errors).

- [ ] **Step 7: Commit**

```bash
git init
git add pyproject.toml .gitignore credentials/.gitkeep src/ tests/
git commit -m "chore: scaffold project"
```

---

## Task 2: Google OAuth2 authentication (`auth.py`)

**Files:**
- Create: `src/mdnotes/auth.py`
- Create: `tests/test_auth.py`

The auth module wraps the OAuth2 installed-app flow. It reads `credentials/client_secret.json` (downloaded from Google Cloud Console), stores the token at `credentials/token.json`, and refreshes automatically.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_auth.py
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from mdnotes.auth import get_drive_service, SCOPES, TOKEN_PATH, CREDS_PATH


def test_scopes_include_drive_readonly():
    assert "https://www.googleapis.com/auth/drive.readonly" in SCOPES


def test_get_drive_service_uses_existing_token(tmp_path, monkeypatch):
    """When a valid token.json exists, it should be loaded without prompting."""
    monkeypatch.setattr("mdnotes.auth.TOKEN_PATH", tmp_path / "token.json")
    monkeypatch.setattr("mdnotes.auth.CREDS_PATH", tmp_path / "client_secret.json")

    mock_creds = MagicMock()
    mock_creds.valid = True

    with patch("mdnotes.auth.Credentials.from_authorized_user_file", return_value=mock_creds) as mock_load, \
         patch("mdnotes.auth.build") as mock_build:
        (tmp_path / "token.json").write_text("{}")
        get_drive_service()
        mock_load.assert_called_once_with(str(tmp_path / "token.json"), SCOPES)
        mock_build.assert_called_once_with("drive", "v3", credentials=mock_creds)


def test_get_drive_service_refreshes_expired_token(tmp_path, monkeypatch):
    """When token is expired but has refresh_token, it should refresh."""
    monkeypatch.setattr("mdnotes.auth.TOKEN_PATH", tmp_path / "token.json")
    monkeypatch.setattr("mdnotes.auth.CREDS_PATH", tmp_path / "client_secret.json")

    mock_creds = MagicMock()
    mock_creds.valid = False
    mock_creds.expired = True
    mock_creds.refresh_token = "some-token"

    with patch("mdnotes.auth.Credentials.from_authorized_user_file", return_value=mock_creds), \
         patch("mdnotes.auth.Request") as mock_request, \
         patch("mdnotes.auth.build"):
        (tmp_path / "token.json").write_text("{}")
        get_drive_service()
        mock_creds.refresh.assert_called_once_with(mock_request())
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_auth.py -v
```

Expected: `ImportError: No module named 'mdnotes.auth'`

- [ ] **Step 3: Implement `auth.py`**

```python
# src/mdnotes/auth.py
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_BASE = Path(__file__).parent.parent.parent  # repo root
TOKEN_PATH = _BASE / "credentials" / "token.json"
CREDS_PATH = _BASE / "credentials" / "client_secret.json"


def get_drive_service():
    """Return an authenticated Google Drive v3 service object."""
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())

    return build("drive", "v3", credentials=creds)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_auth.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mdnotes/auth.py tests/test_auth.py
git commit -m "feat: google oauth2 auth module"
```

---

## Task 3: Google Drive PDF listing and download (`drive.py`)

**Files:**
- Create: `src/mdnotes/drive.py`
- Create: `tests/test_drive.py`

Lists all PDFs inside the GoodNotes folder on Drive (default folder name `GoodNotes 5`), then downloads each one. Skips files whose local copy is already up-to-date by comparing the Drive `modifiedTime`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_drive.py
from unittest.mock import MagicMock, patch, call
from pathlib import Path
import pytest
from mdnotes.drive import list_goodnotes_pdfs, download_pdf, find_goodnotes_folder_id


def test_find_goodnotes_folder_id_returns_id(mock_drive_service):
    mock_drive_service.files().list().execute.return_value = {
        "files": [{"id": "folder123", "name": "GoodNotes 5"}]
    }
    result = find_goodnotes_folder_id(mock_drive_service, folder_name="GoodNotes 5")
    assert result == "folder123"


def test_find_goodnotes_folder_id_raises_when_not_found(mock_drive_service):
    mock_drive_service.files().list().execute.return_value = {"files": []}
    with pytest.raises(FileNotFoundError, match="GoodNotes 5"):
        find_goodnotes_folder_id(mock_drive_service, folder_name="GoodNotes 5")


def test_list_goodnotes_pdfs_returns_file_metadata(mock_drive_service):
    mock_drive_service.files().list().execute.return_value = {
        "files": [
            {"id": "abc", "name": "Math Notes.pdf", "modifiedTime": "2024-01-01T00:00:00.000Z"},
            {"id": "def", "name": "History.pdf", "modifiedTime": "2024-02-01T00:00:00.000Z"},
        ]
    }
    files = list_goodnotes_pdfs(mock_drive_service, folder_id="folder123")
    assert len(files) == 2
    assert files[0]["name"] == "Math Notes.pdf"


def test_download_pdf_writes_file(mock_drive_service, tmp_path):
    """download_pdf should write bytes to output_dir/<name>."""
    mock_media = MagicMock()
    mock_media.next_chunk.side_effect = [(None, False), (None, True)]
    mock_drive_service.files().get_media.return_value = mock_media

    with patch("mdnotes.drive.MediaIoBaseDownload") as MockDL:
        instance = MockDL.return_value
        instance.next_chunk.side_effect = [(None, False), (None, True)]

        path = download_pdf(
            mock_drive_service,
            file_id="abc",
            file_name="Math Notes.pdf",
            output_dir=tmp_path,
        )

    assert path == tmp_path / "Math Notes.pdf"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_drive.py -v
```

Expected: `ImportError: No module named 'mdnotes.drive'`

- [ ] **Step 3: Implement `drive.py`**

```python
# src/mdnotes/drive.py
import io
from pathlib import Path
from googleapiclient.http import MediaIoBaseDownload


def find_goodnotes_folder_id(service, folder_name: str = "GoodNotes 5") -> str:
    """Return the Drive folder ID for the GoodNotes sync folder."""
    result = service.files().list(
        q=f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false",
        fields="files(id, name)",
    ).execute()
    files = result.get("files", [])
    if not files:
        raise FileNotFoundError(f"Google Drive folder '{folder_name}' not found")
    return files[0]["id"]


def list_goodnotes_pdfs(service, folder_id: str) -> list[dict]:
    """Return list of PDF file metadata dicts inside folder_id."""
    result = service.files().list(
        q=f"mimeType='application/pdf' and '{folder_id}' in parents and trashed=false",
        fields="files(id, name, modifiedTime)",
    ).execute()
    return result.get("files", [])


def download_pdf(service, file_id: str, file_name: str, output_dir: Path) -> Path:
    """Download a Drive file by ID to output_dir. Returns the local path."""
    dest = output_dir / file_name
    request = service.files().get_media(fileId=file_id)
    with open(dest, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    return dest
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_drive.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mdnotes/drive.py tests/test_drive.py
git commit -m "feat: drive listing and download"
```

---

## Task 4: Content-hash cache (`cache.py`)

**Files:**
- Create: `src/mdnotes/cache.py`
- Create: `tests/test_cache.py`

Before transcribing a page image, compute its SHA-256 hash. Store `{hash: markdown}` in a JSON cache file (default: `~/.cache/mdnotes/transcriptions.json`). On cache hit, skip the API call entirely. This prevents re-billing for unchanged pages across re-runs.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cache.py
import json
from pathlib import Path
import pytest
from mdnotes.cache import TranscriptionCache


def test_cache_miss_returns_none(tmp_path):
    cache = TranscriptionCache(tmp_path / "cache.json")
    assert cache.get("deadbeef") is None


def test_cache_set_and_get(tmp_path):
    cache = TranscriptionCache(tmp_path / "cache.json")
    cache.set("deadbeef", "# My Notes\n- item")
    assert cache.get("deadbeef") == "# My Notes\n- item"


def test_cache_persists_to_disk(tmp_path):
    path = tmp_path / "cache.json"
    cache1 = TranscriptionCache(path)
    cache1.set("abc123", "some markdown")

    cache2 = TranscriptionCache(path)  # reload from disk
    assert cache2.get("abc123") == "some markdown"


def test_cache_page_hash_is_sha256_of_bytes():
    from mdnotes.cache import page_hash
    data = b"fake image bytes"
    h = page_hash(data)
    import hashlib
    assert h == hashlib.sha256(data).hexdigest()
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_cache.py -v
```

Expected: `ImportError: No module named 'mdnotes.cache'`

- [ ] **Step 3: Implement `cache.py`**

```python
# src/mdnotes/cache.py
import hashlib
import json
from pathlib import Path


def page_hash(image_bytes: bytes) -> str:
    """Return SHA-256 hex digest of image bytes."""
    return hashlib.sha256(image_bytes).hexdigest()


class TranscriptionCache:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._data: dict[str, str] = {}
        if self._path.exists():
            self._data = json.loads(self._path.read_text())

    def get(self, hash_: str) -> str | None:
        return self._data.get(hash_)

    def set(self, hash_: str, markdown: str) -> None:
        self._data[hash_] = markdown
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_cache.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mdnotes/cache.py tests/test_cache.py
git commit -m "feat: sha256 transcription cache"
```

---

## Task 5: PDF rasterization (`rasterize.py`)

**Files:**
- Create: `src/mdnotes/rasterize.py`
- Create: `tests/test_rasterize.py`

Wraps `pdftoppm` (poppler). Takes a PDF path, writes JPEG pages to a temp directory, returns a sorted list of `(page_number, bytes)` tuples. **System requirement:** `poppler-utils` must be installed (`brew install poppler` on macOS).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_rasterize.py
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
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_rasterize.py -v
```

Expected: `ImportError: No module named 'mdnotes.rasterize'`

- [ ] **Step 3: Implement `rasterize.py`**

```python
# src/mdnotes/rasterize.py
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
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_rasterize.py -v
```

Expected: all 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mdnotes/rasterize.py tests/test_rasterize.py
git commit -m "feat: pdf rasterization via pdftoppm"
```

---

## Task 6: Handwriting transcription (`transcribe.py`)

**Files:**
- Create: `src/mdnotes/transcribe.py`
- Create: `tests/test_transcribe.py`

Sends a JPEG page image to Claude Haiku (vision) and returns Markdown. Uses the cache to skip pages already transcribed.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_transcribe.py
import base64
from unittest.mock import MagicMock, patch
import pytest
from mdnotes.transcribe import transcribe_page, transcribe_pdf_pages
from mdnotes.cache import TranscriptionCache


FAKE_IMAGE = b"\xff\xd8\xff" + b"\x00" * 100  # minimal JPEG-like bytes


def _make_cache(tmp_path):
    return TranscriptionCache(tmp_path / "cache.json")


def test_transcribe_page_calls_claude(tmp_path):
    """transcribe_page should call the Anthropic API and return the text."""
    cache = _make_cache(tmp_path)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="# My Notes\n- item 1")]
    )

    result = transcribe_page(FAKE_IMAGE, cache=cache, client=mock_client)

    assert result == "# My Notes\n- item 1"
    mock_client.messages.create.assert_called_once()


def test_transcribe_page_uses_cache_on_second_call(tmp_path):
    """Second call with same image bytes should not call the API."""
    cache = _make_cache(tmp_path)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="cached markdown")]
    )

    # First call — populates cache
    transcribe_page(FAKE_IMAGE, cache=cache, client=mock_client)
    # Second call — should be a cache hit
    result = transcribe_page(FAKE_IMAGE, cache=cache, client=mock_client)

    assert result == "cached markdown"
    assert mock_client.messages.create.call_count == 1  # only called once


def test_transcribe_pdf_pages_stitches_pages(tmp_path):
    """transcribe_pdf_pages should join page markdowns with a separator."""
    cache = _make_cache(tmp_path)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="page content")]
    )

    pages = [(1, FAKE_IMAGE), (2, FAKE_IMAGE + b"\x01")]
    result = transcribe_pdf_pages(pages, cache=cache, client=mock_client)

    assert "---" in result
    assert result.count("page content") == 2
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_transcribe.py -v
```

Expected: `ImportError: No module named 'mdnotes.transcribe'`

- [ ] **Step 3: Implement `transcribe.py`**

```python
# src/mdnotes/transcribe.py
import base64
import anthropic
from mdnotes.cache import TranscriptionCache, page_hash

MODEL = "claude-haiku-4-5"
PROMPT = (
    "Transcribe all handwritten content from this note page into clean Markdown. "
    "Preserve headings, bullet points, numbered lists, and diagrams described as text. "
    "For equations, use LaTeX fenced in $...$. "
    "If a section is illegible, write [illegible]. "
    "Output only the Markdown, no preamble."
)


def transcribe_page(
    image_bytes: bytes,
    cache: TranscriptionCache,
    client: anthropic.Anthropic | None = None,
) -> str:
    """
    Return Markdown for a single page image.
    Uses cache to skip API call when content is unchanged.
    """
    if client is None:
        client = anthropic.Anthropic()

    h = page_hash(image_bytes)
    cached = cache.get(h)
    if cached is not None:
        return cached

    encoded = base64.standard_b64encode(image_bytes).decode()
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": encoded},
                },
                {"type": "text", "text": PROMPT},
            ],
        }],
    )
    markdown = response.content[0].text
    cache.set(h, markdown)
    return markdown


def transcribe_pdf_pages(
    pages: list[tuple[int, bytes]],
    cache: TranscriptionCache,
    client: anthropic.Anthropic | None = None,
) -> str:
    """
    Transcribe all pages of a PDF and return stitched Markdown.
    pages: list of (page_number, image_bytes) tuples.
    """
    parts = [transcribe_page(img, cache=cache, client=client) for _, img in pages]
    return "\n\n---\n\n".join(parts)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_transcribe.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mdnotes/transcribe.py tests/test_transcribe.py
git commit -m "feat: claude vision transcription with cache"
```

---

## Task 7: Pipeline orchestration (`pipeline.py`)

**Files:**
- Create: `src/mdnotes/pipeline.py`
- Create: `tests/test_pipeline.py`

Ties together auth → drive → rasterize → transcribe. Accepts `output_dir` for `.md` files and `cache_path`. Skips downloading files whose local `.md` is already newer than the Drive `modifiedTime`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pipeline.py
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from mdnotes.pipeline import run_pipeline, PipelineResult


def test_run_pipeline_creates_markdown_files(tmp_path):
    """End-to-end: one PDF produces one .md file."""
    pdf_path = tmp_path / "Math Notes.pdf"
    pdf_path.write_bytes(b"%PDF fake")

    mock_service = MagicMock()

    with patch("mdnotes.pipeline.find_goodnotes_folder_id", return_value="folder1"), \
         patch("mdnotes.pipeline.list_goodnotes_pdfs", return_value=[
             {"id": "f1", "name": "Math Notes.pdf", "modifiedTime": "2024-01-01T00:00:00.000Z"}
         ]), \
         patch("mdnotes.pipeline.download_pdf", return_value=pdf_path), \
         patch("mdnotes.pipeline.rasterize_pdf", return_value=[(1, b"img")]), \
         patch("mdnotes.pipeline.transcribe_pdf_pages", return_value="# Math Notes\n- item"):

        result = run_pipeline(
            service=mock_service,
            output_dir=tmp_path,
            cache_path=tmp_path / "cache.json",
        )

    md_path = tmp_path / "Math Notes.md"
    assert md_path.exists()
    assert md_path.read_text() == "# Math Notes\n- item"
    assert result.processed == ["Math Notes.pdf"]
    assert result.skipped == []


def test_run_pipeline_skips_up_to_date_files(tmp_path):
    """If .md exists and is newer than Drive modifiedTime, skip the file."""
    md_path = tmp_path / "Math Notes.md"
    md_path.write_text("already done")

    import os, time
    # set mtime to "now" so it's newer than the Drive timestamp
    os.utime(md_path, None)

    mock_service = MagicMock()

    with patch("mdnotes.pipeline.find_goodnotes_folder_id", return_value="folder1"), \
         patch("mdnotes.pipeline.list_goodnotes_pdfs", return_value=[
             {"id": "f1", "name": "Math Notes.pdf", "modifiedTime": "2020-01-01T00:00:00.000Z"}
         ]), \
         patch("mdnotes.pipeline.download_pdf") as mock_dl, \
         patch("mdnotes.pipeline.rasterize_pdf"), \
         patch("mdnotes.pipeline.transcribe_pdf_pages"):

        result = run_pipeline(
            service=mock_service,
            output_dir=tmp_path,
            cache_path=tmp_path / "cache.json",
        )

    mock_dl.assert_not_called()
    assert result.skipped == ["Math Notes.pdf"]
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_pipeline.py -v
```

Expected: `ImportError: No module named 'mdnotes.pipeline'`

- [ ] **Step 3: Implement `pipeline.py`**

```python
# src/mdnotes/pipeline.py
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import anthropic

from mdnotes.cache import TranscriptionCache
from mdnotes.drive import find_goodnotes_folder_id, list_goodnotes_pdfs, download_pdf
from mdnotes.rasterize import rasterize_pdf
from mdnotes.transcribe import transcribe_pdf_pages

DEFAULT_CACHE = Path.home() / ".cache" / "mdnotes" / "transcriptions.json"
_DT_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


@dataclass
class PipelineResult:
    processed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _drive_mtime(modified_time_str: str) -> datetime:
    try:
        return datetime.strptime(modified_time_str, _DT_FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        # Fallback: strip fractional seconds
        return datetime.strptime(modified_time_str[:19] + "Z", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def run_pipeline(
    service,
    output_dir: Path,
    folder_name: str = "GoodNotes 5",
    cache_path: Path = DEFAULT_CACHE,
    dpi: int = 150,
) -> PipelineResult:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cache = TranscriptionCache(cache_path)
    client = anthropic.Anthropic()
    result = PipelineResult()

    folder_id = find_goodnotes_folder_id(service, folder_name=folder_name)
    pdf_files = list_goodnotes_pdfs(service, folder_id=folder_id)

    for file_meta in pdf_files:
        name = file_meta["name"]
        stem = Path(name).stem
        md_path = output_dir / f"{stem}.md"

        # Skip if local markdown is newer than Drive file
        drive_mtime = _drive_mtime(file_meta["modifiedTime"])
        if md_path.exists():
            local_mtime = datetime.fromtimestamp(md_path.stat().st_mtime, tz=timezone.utc)
            if local_mtime > drive_mtime:
                result.skipped.append(name)
                continue

        try:
            pdf_path = download_pdf(service, file_id=file_meta["id"], file_name=name, output_dir=output_dir)
            pages = rasterize_pdf(pdf_path, dpi=dpi)
            markdown = transcribe_pdf_pages(pages, cache=cache, client=client)
            md_path.write_text(markdown)
            pdf_path.unlink(missing_ok=True)  # clean up downloaded PDF
            result.processed.append(name)
        except Exception as exc:
            result.errors.append(f"{name}: {exc}")

    return result
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_pipeline.py -v
```

Expected: all 2 tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/mdnotes/pipeline.py tests/test_pipeline.py
git commit -m "feat: pipeline orchestration with staleness check"
```

---

## Task 8: CLI entry point (`cli.py`)

**Files:**
- Create: `src/mdnotes/cli.py`
- Create: `tests/test_cli.py`

Provides `mdnotes sync [OPTIONS]`. Options: `--output-dir` (default: `~/notes/`), `--folder-name` (default: `GoodNotes 5`), `--dpi` (default: 150), `--cache` (default: `~/.cache/mdnotes/transcriptions.json`).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli.py
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from mdnotes.cli import main


def test_sync_command_exists():
    runner = CliRunner()
    result = runner.invoke(main, ["sync", "--help"])
    assert result.exit_code == 0
    assert "--output-dir" in result.output
    assert "--folder-name" in result.output
    assert "--dpi" in result.output


def test_sync_command_runs_pipeline(tmp_path):
    mock_result = MagicMock()
    mock_result.processed = ["A.pdf"]
    mock_result.skipped = []
    mock_result.errors = []

    with patch("mdnotes.cli.get_drive_service") as mock_auth, \
         patch("mdnotes.cli.run_pipeline", return_value=mock_result) as mock_pipeline:
        runner = CliRunner()
        result = runner.invoke(main, ["sync", "--output-dir", str(tmp_path)])

    assert result.exit_code == 0
    mock_pipeline.assert_called_once()
    assert "A.pdf" in result.output


def test_sync_command_reports_errors(tmp_path):
    mock_result = MagicMock()
    mock_result.processed = []
    mock_result.skipped = []
    mock_result.errors = ["B.pdf: rasterize failed"]

    with patch("mdnotes.cli.get_drive_service"), \
         patch("mdnotes.cli.run_pipeline", return_value=mock_result):
        runner = CliRunner()
        result = runner.invoke(main, ["sync", "--output-dir", str(tmp_path)])

    assert "B.pdf: rasterize failed" in result.output
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_cli.py -v
```

Expected: `ImportError: No module named 'mdnotes.cli'`

- [ ] **Step 3: Implement `cli.py`**

```python
# src/mdnotes/cli.py
from pathlib import Path
import click
from mdnotes.auth import get_drive_service
from mdnotes.pipeline import run_pipeline, DEFAULT_CACHE


@click.group()
def main():
    """mdnotes — sync GoodNotes PDFs from Drive and transcribe to Markdown."""


@main.command()
@click.option("--output-dir", default=str(Path.home() / "notes"), show_default=True,
              help="Directory to write .md files into.")
@click.option("--folder-name", default="GoodNotes 5", show_default=True,
              help="Name of the GoodNotes folder in Google Drive.")
@click.option("--dpi", default=150, show_default=True,
              help="Rasterization DPI (higher = better quality, more tokens).")
@click.option("--cache", default=str(DEFAULT_CACHE), show_default=True,
              help="Path to transcription cache JSON.")
def sync(output_dir, folder_name, dpi, cache):
    """Download PDFs from Google Drive and transcribe handwriting to Markdown."""
    service = get_drive_service()
    result = run_pipeline(
        service=service,
        output_dir=Path(output_dir),
        folder_name=folder_name,
        cache_path=Path(cache),
        dpi=dpi,
    )

    if result.processed:
        click.echo(f"Transcribed: {', '.join(result.processed)}")
    if result.skipped:
        click.echo(f"Skipped (up-to-date): {', '.join(result.skipped)}")
    if result.errors:
        click.echo("Errors:", err=True)
        for e in result.errors:
            click.echo(f"  {e}", err=True)
```

- [ ] **Step 4: Run all tests**

```bash
pytest -v
```

Expected: all tests PASS.

- [ ] **Step 5: Smoke test the CLI (requires real credentials)**

```bash
mdnotes --help
mdnotes sync --help
```

Expected: help text prints cleanly with all options listed.

- [ ] **Step 6: Commit**

```bash
git add src/mdnotes/cli.py tests/test_cli.py
git commit -m "feat: cli sync command"
```

---

## Task 9: First real run + README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Install poppler**

```bash
brew install poppler
pdftoppm -v   # should print version
```

- [ ] **Step 2: Create Google Cloud credentials**

1. Go to https://console.cloud.google.com → New project
2. Enable **Google Drive API**
3. Create **OAuth 2.0 Client ID** → Application type: Desktop app
4. Download JSON → save to `credentials/client_secret.json`

- [ ] **Step 3: Set your Anthropic API key**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Or add to `~/.zshrc` / `~/.bashrc`.

- [ ] **Step 4: Run a real sync**

```bash
mdnotes sync --output-dir ./output
```

First run opens a browser for Google OAuth. Approve access. Subsequent runs use the saved token.

- [ ] **Step 5: Inspect output**

```bash
ls ./output/*.md
cat "./output/Math Notes.md"
```

- [ ] **Step 6: Write `README.md`**

```markdown
# mdnotes

Sync GoodNotes PDFs from Google Drive and transcribe handwriting to Markdown via Claude vision.

## Setup

### System dependency

```bash
brew install poppler
```

### Python

```bash
pip install -e .
```

### Google credentials

1. Create a project at https://console.cloud.google.com
2. Enable the Google Drive API
3. Create an OAuth 2.0 Desktop app client ID
4. Download the JSON and save to `credentials/client_secret.json`

### Anthropic API key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

```bash
mdnotes sync                          # writes to ~/notes/
mdnotes sync --output-dir ./output
mdnotes sync --folder-name "GoodNotes 5" --dpi 200
```

## Cost

~$0.013 per 10-page notebook at 150 DPI (Claude Haiku vision pricing).
Transcriptions are cached by content hash — re-running is free for unchanged pages.
```

- [ ] **Step 7: Final commit**

```bash
git add README.md
git commit -m "docs: readme and setup instructions"
```

---

## Self-Review

**Spec coverage check:**
- [x] Google Drive auth (Task 2)
- [x] PDF download with staleness check (Task 3, 7)
- [x] PDF → image rasterization (Task 5)
- [x] Image → Markdown via cheap vision model (Task 6)
- [x] Caching to avoid re-billing (Task 4, 6)
- [x] Markdown output files (Task 7)
- [x] CLI for orchestration (Task 8)
- [x] Cost-conscious model choice (claude-haiku-4-5 used in Task 6)

**Placeholder scan:** No TBDs, TODOs, or vague steps found.

**Type consistency:** `TranscriptionCache` used consistently across Task 4, 6, 7. `PipelineResult` dataclass defined in Task 7, used in Task 8. `rasterize_pdf` returns `list[tuple[int, bytes]]` — consumed correctly in `transcribe_pdf_pages` in Task 6 and Task 7.
