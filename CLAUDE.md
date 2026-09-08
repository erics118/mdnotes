# mdnotes project instructions

## Git

Commit changes as they make logical sense — don't wait for the user to ask. Always let the user know when a commit is made.

## Project Overview

`mdnotes` is a GUI web app that syncs GoodNotes-exported PDFs from Google Drive, transcribes handwritten pages to Markdown with Claude Haiku vision (invisible plumbing for search), and lets you browse and hybrid-search your notes, opening a result as the original PDF jumped to the hit page. Course is the primary navigation axis. The transcription output feeds the search index; you read the PDF, not the Markdown.

The UI is a React SPA (`web/`) served by the FastAPI backend (`server.py`). Everything is in-browser: connect Google Drive, pick the GoodNotes folder (any depth), choose which subfolders to sync/ignore, run/stop a sync with live progress, then search. The CLI (`cli.py`) still exists for scripted/headless use but is no longer the primary interface.

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
pip install -e ".[dev]"        # backend + dev deps (pytest)
npm --prefix web install       # frontend deps (nodejs_22 via flake)
npm --prefix web run build     # produce src/mdnotes/web_dist (served by FastAPI, bundled into the wheel)
```

Environment variables go in `.envrc` (gitignored via direnv). API keys are read via `config.py`, which prefers the `MDNOTES_`-prefixed names and falls back to the unprefixed ones:
```
export MDNOTES_ANTHROPIC_API_KEY=sk-ant-...   # transcription (Claude Haiku vision)
export MDNOTES_VOYAGE_API_KEY=pa-...          # embeddings + rerank
source venv/bin/activate
```

Google OAuth credentials go in `credentials/` (gitignored):
- `credentials/client_secret.json` — OAuth client secret from Google Cloud Console
- `credentials/token.json` — auto-generated on first auth (via the Setup wizard or CLI)

## Running

Primary (GUI):
```bash
mdnotes serve                  # FastAPI + React SPA on http://127.0.0.1:8000
```
Then in the browser: Setup connects Drive, browses to and selects the GoodNotes folder, and marks folders to Sync/Ignore; run Sync with live progress; Search reads results as PDFs. Set `MDNOTES_PASSWORD` to require a single password. The SPA is served from `src/mdnotes/web_dist`, so build the frontend first.

CLI (scripted/headless, still supported):
```bash
mdnotes sync --output-dir ~/.local/share/mdnotes/notes
mdnotes index / search / ingest-pdf
mdnotes prefs   # inspect remembered folder sync preferences
```

## Module Responsibilities

| File | Responsibility |
|------|---------------|
| `config.py` | Reads `MDNOTES_`-prefixed API keys (fallback to unprefixed); `DEFAULT_NOTES` (`~/.local/share/mdnotes/notes`) |
| `fsutil.py` | `atomic_write_text` (temp + fsync + os.replace), `read_json` (corrupt-safe load), `safe_component` (confine Drive names to one path component) |
| `cli.py` | Click CLI — `sync`, `index`, `search`, `ingest-pdf`, `serve`, `prefs` |
| `pipeline.py` | Orchestration: Drive walk, staleness checks, download, resume, transcription loop; `progress`/`should_stop`/`root_id` for the GUI |
| `drive.py` | Google Drive API: `list_folder_children` (browse any depth), `walk_folders`, `find_goodnotes_folder_id`, list items, download PDF |
| `rasterize.py` | `pdf_page_count`, `pdf_page_hash` (SHA-256 of raw content stream), `rasterize_page` (pdftoppm → JPEG bytes) |
| `transcribe.py` | Claude Haiku vision call; `transcribe_page` accepts a `cache_key` to decouple hash from image bytes |
| `notefmt.py` | Owns the `.md` file format: frontmatter + page-block parse/build (source of truth) |
| `cache.py` | `TranscriptionCache` — JSON dict on disk, keyed by page hash |
| `auth.py` | Google OAuth2 flow, returns Drive service |
| `prefs.py` | Folder sync preferences (`yes`/`no`) and settings (`folder_id`, `folder_name`, `output_dir`) in `~/.config/mdnotes/prefs.json` |
| `embed.py` | Voyage embeddings + rerank wrappers (`voyage-4-lite`, `rerank-3-lite`); optional `VOYAGE_MIN_INTERVAL` throttle |
| `index.py` | `NoteIndex`: derived SQLite search index (FTS5 BM25 + sqlite-vec KNN), embedding cache |
| `search.py` | Hybrid retrieval: vector + FTS candidates, RRF fusion, Voyage rerank |
| `server.py` | FastAPI backend: status, auth, Drive browse, folder prefs, sync (start/stop/progress), search/notes/note/pdf; serves the React SPA from `src/mdnotes/web_dist`; single-password auth |
| `textbook.py` | Ingest printed PDFs via `pdftotext` (no VLM) into the unified index |
| `web/` | React + Vite + TypeScript SPA (TanStack Query, React Router, Tailwind). Pages: Search, Folders, Setup, Reader. Built to `src/mdnotes/web_dist` (inside the package, so `pip install` ships it), served by `server.py`. |

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
| `~/.local/share/mdnotes/notes/` | Default output directory (`config.DEFAULT_NOTES`) |
