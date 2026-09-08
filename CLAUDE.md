# mdnotes project instructions

## Git

Commit changes as they make logical sense — don't wait for the user to ask. Always let the user know when a commit is made.

## Project Overview

`mdnotes` syncs GoodNotes-exported PDFs from Google Drive and transcribes handwritten pages to Markdown using Claude Haiku vision. Output `.md` files are intended for LLM ingestion and Obsidian.

Pipeline per PDF:
1. Check if local `.md` is up-to-date vs Drive `modifiedTime` (via embedded header)
2. Download PDF to temp dir (or output dir for real sync)
3. For each page: hash raw PDF content stream → check transcription cache → rasterize + transcribe on miss
4. Write `.md` incrementally with in-progress marker; replace with final file on completion

## System Dependencies

`pdftoppm` (from poppler) must be installed:
```bash
brew install poppler   # macOS
```

## Dev Setup

```bash
pip install -e ".[dev]"    # install with dev dependencies (pytest)
```

Environment variables go in `.envrc` (gitignored via direnv):
```
export ANTHROPIC_API_KEY=sk-ant-...
source venv/bin/activate
```

Google OAuth credentials go in `credentials/` (gitignored):
- `credentials/credentials.json` — OAuth client secret from Google Cloud Console
- `credentials/token.json` — auto-generated on first auth

## Running

```bash
mdnotes sync --folder-name "GoodNotes 5" --output-dir ~/notes
mdnotes sync --folder-name "GoodNotes 5" --output-dir ~/notes --dry-run
mdnotes sync --folder-name "GoodNotes 5" --output-dir ~/notes --only-download
mdnotes prefs   # interactive viewer for remembered folder sync preferences
```

## Module Responsibilities

| File | Responsibility |
|------|---------------|
| `cli.py` | Click CLI — `sync` and `prefs` subcommands |
| `pipeline.py` | Orchestration: Drive walk, staleness checks, download, resume, transcription loop |
| `drive.py` | Google Drive API: find folder, list items, download PDF |
| `rasterize.py` | `pdf_page_count`, `pdf_page_hash` (SHA-256 of raw content stream), `rasterize_page` (pdftoppm → JPEG bytes) |
| `transcribe.py` | Claude Haiku vision call; `transcribe_page` accepts a `cache_key` to decouple hash from image bytes |
| `notefmt.py` | Owns the `.md` file format: frontmatter + page-block parse/build (source of truth) |
| `cache.py` | `TranscriptionCache` — JSON dict on disk, keyed by page hash |
| `auth.py` | Google OAuth2 flow, returns Drive service |
| `prefs.py` | Folder sync preferences (`yes`/`no`/`select`) persisted to `~/.config/mdnotes/prefs.json` |
| `embed.py` | Voyage embeddings + rerank wrappers (`voyage-4-lite`, `rerank-3-lite`); optional `VOYAGE_MIN_INTERVAL` throttle |
| `index.py` | `NoteIndex`: derived SQLite search index (FTS5 BM25 + sqlite-vec KNN), embedding cache |
| `search.py` | Hybrid retrieval: vector + FTS candidates, RRF fusion, Voyage rerank |
| `server.py` | FastAPI backend (`/api/search`, `/api/notes`, `/api/note`) + serves `web/`; single-password auth |
| `textbook.py` | Ingest printed PDFs via `pdftotext` (no VLM) into the unified index |

## Output File Format Contracts

The note file format is owned by `notefmt.py` (`parse_frontmatter`, `parse_pages`, `build_note`). All read/write of the format goes through it; the search index is derived from these files. Reads stay backward-compatible with the pre-frontmatter `<!-- mdnotes: synced/in progress -->` comment headers.

`drive_mtime` records the source PDF version so staleness/resume can detect a changed PDF; `status: in_progress` marks an interrupted sync (always re-synced next run). Page blocks are `<!-- page N/total -->` delimited, joined by `\n\n---\n\n`; the page regex requires the separator to be followed by a page marker, so a bare `---` inside transcribed content does not split a page.

**Completed file:**
```
---
source_type: handwritten
drive_mtime: 2026-04-15T12:00:00.000000Z
synced: 2026-04-15T12:34:56.000000Z
---

<!-- page 1/3 -->
...markdown...

---

<!-- page 2/3 -->
...markdown...
```

**In-progress file** (interrupted sync):
```
---
source_type: handwritten
drive_mtime: 2026-04-15T12:00:00.000000Z
status: in_progress
---

<!-- page 1/3 -->
...markdown...
```

## Cache Key Format

- **Transcription:** `{sha256_of_pdf_page_content_stream}:dpi={dpi}:v={TRANSCRIBE_VERSION}` — stable across re-downloads; DPI and `TRANSCRIBE_VERSION` (in `transcribe.py`) are part of the key, so changing DPI, the prompt, or the model invalidates cached transcriptions. Bump `TRANSCRIBE_VERSION` whenever `PROMPT` or `MODEL` changes.
- **Download check** (only_download mode): `__dl_check__:{file_id}:{drive_mtime}` — records that a PDF version was checked; prevents re-downloading on repeated `--only-download` runs

## Model

`claude-haiku-4-5` — cheapest Claude vision model. Configured in `transcribe.py`. Estimated ~$0.001–0.003 per page at 150 DPI for math/handwriting notes.

## Default Paths

| Path | Purpose |
|------|---------|
| `~/.cache/mdnotes/transcriptions.json` | Transcription + download-check cache |
| `~/.config/mdnotes/prefs.json` | Folder sync preferences |
| `~/notes/` | Default output directory |
