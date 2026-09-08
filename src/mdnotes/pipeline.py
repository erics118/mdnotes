# src/mdnotes/pipeline.py
import re
import tempfile
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import anthropic

from mdnotes.cache import TranscriptionCache
from mdnotes.config import anthropic_key
from mdnotes.drive import find_goodnotes_folder_id, list_items, download_pdf
from mdnotes.fsutil import atomic_write_text, safe_component
from mdnotes.prefs import SyncPrefs, YES, NO, SELECT
from mdnotes.notefmt import HANDWRITTEN, TEXTBOOK, build_note, page_block, parse_frontmatter, parse_pages
from mdnotes.rasterize import pdf_page_count, pdf_page_hash, rasterize_page
from mdnotes.transcribe import transcribe_page, read_cached, TRANSCRIBE_VERSION
from mdnotes.textbook import extract_pdf_pages, has_text_layer

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


def _rel(md_path: Path, root_output: Path | None) -> str:
    try:
        return md_path.relative_to(root_output).as_posix() if root_output else md_path.name
    except Exception:
        return md_path.name


def _is_up_to_date(file_meta: dict, md_path: Path) -> bool:
    """Return True if local .md was synced from the same (or newer) Drive version and is complete."""
    if not md_path.exists():
        return False
    text = md_path.read_text()
    current = _drive_mtime(file_meta["modifiedTime"])

    meta, _ = parse_frontmatter(text)
    if meta:
        if meta.get("status") == "in_progress":
            return False
        recorded = meta.get("drive_mtime")
        if recorded:
            return _drive_mtime(recorded) >= current

    # Legacy comment-format fallback (files written before frontmatter)
    if "<!-- mdnotes: in progress" in text:
        return False
    m = re.search(r"<!-- mdnotes: synced: ([^-].*?) -->", text)
    if m:
        return _drive_mtime(m.group(1)) >= current
    # No recorded Drive provenance (old single-block format): re-sync to re-transcribe properly
    return False


def _ask_folder(name: str, indent: str, folder_id: str, prefs: SyncPrefs,
                full_path: str) -> str:
    """
    Ask what to do with a folder. Returns "yes", "no", or "select".
    Checks stored preferences first; if remembered, uses that without prompting.
    full_path: slash-separated path used as the human-readable label in saved prefs
               e.g. "GoodNotes 5 / MATH / Linear Algebra"
    """
    stored = prefs.get(folder_id)
    if stored == YES:
        print(f"{indent}Folder '{name}' → syncing all (remembered)")
        return YES
    if stored == NO:
        print(f"{indent}Folder '{name}' → skipping (remembered)")
        return NO
    if stored == SELECT:
        print(f"{indent}Folder '{name}' → selecting (remembered)")
        return SELECT

    while True:
        raw = input(f"{indent}Folder '{name}'? [y/n/s] (uppercase to remember): ").strip()
        choice = raw.lower()
        remember = raw.isupper() and len(raw) == 1
        if choice == "y":
            if remember:
                prefs.set(folder_id, YES, name=full_path)
                print(f"{indent}  (remembered)")
            return YES
        if choice == "n":
            if remember:
                prefs.set(folder_id, NO, name=full_path)
                print(f"{indent}  (remembered)")
            return NO
        if choice == "s":
            if remember:
                prefs.set(folder_id, SELECT, name=full_path)
                print(f"{indent}  (remembered)")
            return SELECT


def _sync_file(service, file_meta: dict, output_dir: Path, cache: TranscriptionCache,
               client: anthropic.Anthropic, result: PipelineResult, dpi: int, indent: str,
               only_download: bool = False, note_index=None, root_output: Path | None = None,
               progress=None, should_stop=None) -> None:
    """Download, rasterize, transcribe, and save one PDF, page by page with cache.

    only_download: download and check per-page cache but skip transcription and writing.
    """
    name = file_meta["name"]
    stem = safe_component(Path(name).stem)
    md_path = output_dir / f"{stem}.md"

    if _is_up_to_date(file_meta, md_path):
        print(f"{indent}  '{name}' — up-to-date, skipping")
        result.skipped.append(name)
        return

    # For only_download: skip if we've already checked this exact PDF version
    check_key = f"__dl_check__:{file_meta['id']}:{file_meta['modifiedTime']}" if only_download else None
    if check_key and cache.get(check_key) is not None:
        print(f"{indent}  '{name}' — already checked, skipping")
        result.skipped.append(name)
        return

    # In only_download mode, use a temp dir that auto-cleans on exit (even on exception)
    with (tempfile.TemporaryDirectory() if only_download else nullcontext()) as _tmp:
        download_dir = Path(_tmp) if only_download else output_dir

        try:
            print(f"{indent}  Downloading '{name}'...")
            # save the PDF as the .md sibling so the reader can find it; a temp name is fine for only_download
            dl_name = name if only_download else f"{stem}.pdf"
            pdf_path = download_pdf(service, file_id=file_meta["id"], file_name=dl_name, output_dir=download_dir)

            total = pdf_page_count(pdf_path)
            print(f"{indent}  {total} page{'s' if total != 1 else ''}:")
            if progress:
                progress({"type": "file", "name": name, "path": _rel(md_path, root_output),
                          "page": 0, "pages": total})

            # Printed PDFs (textbooks, exam solutions) already have a text layer; extract
            # it with poppler instead of sending hundreds of pages to Claude vision.
            if not only_download and has_text_layer(pdf_path):
                print(f"{indent}  text layer detected - extracting as printed PDF (no vision)")
                tb_pages = extract_pdf_pages(pdf_path)
                synced = datetime.now(timezone.utc).strftime(_DT_FMT)
                blocks = [page_block(p["page_num"], p["total"], p["markdown"]) for p in tb_pages]
                atomic_write_text(md_path, build_note(
                    {"source_type": TEXTBOOK,
                     "drive_mtime": file_meta["modifiedTime"],
                     "synced": synced},
                    blocks,
                ))
                result.processed.append(name)
                print(f"{indent}  Done (text layer) -> {md_path}")
                if progress:
                    progress({"type": "done", "name": name, "path": _rel(md_path, root_output)})
                if note_index is not None and root_output is not None:
                    try:
                        note_index.upsert_note(
                            md_path.relative_to(root_output).as_posix(), title=md_path.stem,
                            pages=tb_pages, path=str(md_path), source_type=TEXTBOOK,
                            drive_mtime=file_meta["modifiedTime"],
                        )
                        print(f"{indent}  Indexed")
                    except Exception as ie:
                        print(f"{indent}  Index error: {ie}")
                        result.errors.append(f"{name} (index): {ie}")
                return

            uncached = 0

            # Recover already-written pages from an interrupted previous run
            pages_done = []
            resume_from = 1
            if not only_download and md_path.exists():
                existing = md_path.read_text()
                meta, _ = parse_frontmatter(existing)
                interrupted = meta.get("status") == "in_progress" or "<!-- mdnotes: in progress" in existing
                if interrupted:
                    recorded = meta.get("drive_mtime")
                    if recorded is None:
                        m = re.search(r"<!-- mdnotes: in progress: (\S+?) -->", existing)
                        recorded = m.group(1) if m else None
                    if recorded == file_meta["modifiedTime"]:
                        parsed = parse_pages(existing)
                        if parsed:
                            pages_done = [page_block(p["page_num"], p["total"], p["markdown"], p.get("search_context", "")) for p in parsed]
                            resume_from = len(pages_done) + 1
                            print(f"{indent}  Resuming from page {resume_from}/{total} ({len(pages_done)} already written)")
                    else:
                        print(f"{indent}  PDF changed since last interrupted run — starting fresh")

            for page_num in range(1, total + 1):
                if page_num < resume_from:
                    print(f"{indent}    Page {page_num}/{total} — already written")
                    continue
                if should_stop and should_stop():
                    print(f"{indent}  stop requested, leaving '{name}' in progress")
                    return
                if progress:
                    progress({"type": "page", "name": name, "path": _rel(md_path, root_output),
                              "page": page_num, "pages": total})

                key = f"{pdf_page_hash(pdf_path, page_num)}:dpi={dpi}:v={TRANSCRIBE_VERSION}"
                hit = read_cached(cache, key)
                if hit is not None:
                    print(f"{indent}    Page {page_num}/{total} — cached")
                    page_md, page_ctx = hit
                else:
                    uncached += 1
                    if only_download:
                        print(f"{indent}    Page {page_num}/{total} — would transcribe")
                        continue
                    else:
                        print(f"{indent}    Page {page_num}/{total} — transcribing...")
                        img = rasterize_page(pdf_path, page_num, dpi=dpi)
                        page_md, page_ctx = transcribe_page(img, cache=cache, client=client, cache_key=key)

                if not only_download:
                    pages_done.append(page_block(page_num, total, page_md, page_ctx))
                    # Rewrite after each page; frontmatter status marks it incomplete
                    # drive_mtime lets resume detect whether the PDF changed
                    md_path.write_text(build_note(
                        {"source_type": HANDWRITTEN,
                         "drive_mtime": file_meta["modifiedTime"],
                         "status": "in_progress"},
                        pages_done,
                    ))

            # normal sync keeps the PDF next to the .md so the web reader can show it;
            # only_download's pdf lives in _tmp and is cleaned up by the context manager

            if only_download:
                if uncached:
                    print(f"{indent}  {uncached} page{'s' if uncached != 1 else ''} would be transcribed")
                    result.processed.append(name)
                else:
                    print(f"{indent}  All pages cached — nothing to transcribe")
                    result.skipped.append(name)
                # Record check so future only_download runs skip re-downloading this version
                cache.set(check_key, "1")
            else:
                # Write final file: frontmatter (no in-progress status) then page blocks
                synced = datetime.now(timezone.utc).strftime(_DT_FMT)
                final_text = build_note(
                    {"source_type": HANDWRITTEN,
                     "drive_mtime": file_meta["modifiedTime"],
                     "synced": synced},
                    pages_done,
                )
                # atomic so an interrupt can't leave a truncated file that reads as complete
                atomic_write_text(md_path, final_text)
                result.processed.append(name)
                print(f"{indent}  Done → {md_path}")
                if progress:
                    progress({"type": "done", "name": name, "path": _rel(md_path, root_output)})
                if note_index is not None and root_output is not None:
                    try:
                        note_id = md_path.relative_to(root_output).as_posix()
                        note_index.upsert_note(
                            note_id, title=md_path.stem, pages=parse_pages(final_text),
                            path=str(md_path), source_type=HANDWRITTEN,
                            drive_mtime=file_meta["modifiedTime"],
                        )
                        print(f"{indent}  Indexed")
                    except Exception as ie:
                        print(f"{indent}  Index error: {ie}")
                        result.errors.append(f"{name} (index): {ie}")
        except anthropic.AuthenticationError:
            # a bad API key is fatal for the whole run; don't grind through every file
            raise
        except Exception as exc:
            print(f"{indent}  Error: {exc}")
            result.errors.append(f"{name}: {exc}")


def _sync_folder(service, folder_id: str, folder_name: str, output_dir: Path,
                 cache: TranscriptionCache, client: anthropic.Anthropic,
                 prefs: SyncPrefs, result: PipelineResult, dpi: int,
                 indent: str = "", mode: str | None = None,
                 dry_run: bool = False, only_download: bool = False,
                 folder_path: str | None = None, assume_yes: bool = False,
                 note_index=None, root_output: Path | None = None,
                 exclude: set[str] | None = None,
                 interactive: bool = True, default_choice: str = NO,
                 progress=None, should_stop=None) -> None:
    """
    Recursively sync a Drive folder.
    mode: "yes" = sync all without asking, "no" = skip all, None = ask
    dry_run: prompts work normally but nothing is downloaded or transcribed
    only_download: download and check per-page cache but skip transcription
    folder_path: full slash-separated path for display in saved prefs
    """
    full_path = folder_path or folder_name
    if exclude and folder_name in exclude:
        print(f"{indent}Folder '{folder_name}' excluded, skipping")
        result.skipped.append(folder_name)
        return
    # an explicit "ignore" on this folder always wins, even when a parent folder is
    # marked "sync" and propagated mode=YES down to here
    if not assume_yes and prefs.get(folder_id) == NO:
        print(f"{indent}Folder '{folder_name}' ignored (explicit), skipping")
        result.skipped.append(folder_name)
        return
    subfolders, pdfs = list_items(service, folder_id)

    if mode is None:
        if not subfolders and not pdfs:
            print(f"{indent}Folder '{folder_name}' is empty, skipping")
            return
        if assume_yes:
            mode = YES
        elif not interactive:
            # web/scheduled sync: no prompting, so only an explicit yes/no counts;
            # SELECT (interactive-only) and no pref fall back to default_choice
            stored = prefs.get(folder_id)
            mode = stored if stored in (YES, NO) else default_choice
        else:
            mode = _ask_folder(folder_name, indent, folder_id, prefs, full_path=full_path)

    if mode == NO:
        result.skipped.append(folder_name)
        return

    folder_output = output_dir / safe_component(folder_name)
    if not dry_run:
        folder_output.mkdir(parents=True, exist_ok=True)

    # Recurse into subfolders
    for sub in subfolders:
        if should_stop and should_stop():
            return
        _sync_folder(
            service, sub["id"], sub["name"], folder_output,
            cache, client, prefs, result, dpi,
            indent=indent + "  ",
            mode=mode if mode == YES else None,  # propagate "yes" but re-ask in "select"/"no" mode
            dry_run=dry_run, only_download=only_download,
            folder_path=f"{full_path} / {sub['name']}",
            assume_yes=assume_yes, note_index=note_index, root_output=root_output,
            exclude=exclude, interactive=interactive, default_choice=default_choice,
            progress=progress, should_stop=should_stop,
        )

    # Sync PDFs
    for pdf in pdfs:
        if should_stop and should_stop():
            return
        name = pdf["name"]
        stem = safe_component(Path(name).stem)
        md_path = folder_output / f"{stem}.md"

        if mode == SELECT:
            if _is_up_to_date(pdf, md_path):
                print(f"{indent}  '{name}' — up-to-date, skipping")
                result.skipped.append(name)
                continue
            answer = input(f"{indent}  Sync '{name}'? [y/N] ").strip().lower()
            if answer != "y":
                print(f"{indent}  Skipping '{name}'")
                result.skipped.append(name)
                continue

        if dry_run:
            if _is_up_to_date(pdf, md_path):
                print(f"{indent}  '{name}' — up-to-date")
                result.skipped.append(name)
            else:
                print(f"{indent}  '{name}' — would sync")
                result.processed.append(name)
        else:
            _sync_file(service, pdf, folder_output, cache, client, result, dpi, indent,
                       only_download=only_download, note_index=note_index, root_output=root_output,
                       progress=progress, should_stop=should_stop)


def run_pipeline(
    service,
    output_dir: Path,
    folder_name: str,
    cache_path: Path = DEFAULT_CACHE,
    dpi: int = 150,
    dry_run: bool = False,
    only_download: bool = False,
    assume_yes: bool = False,
    index_path: Path | None = None,
    exclude: set[str] | None = None,
    interactive: bool = True,
    default_choice: str = NO,
    progress=None,
    should_stop=None,
    root_id: str | None = None,
) -> PipelineResult:
    output_dir = Path(output_dir)
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
    exclude = set(exclude or [])

    cache = TranscriptionCache(cache_path)
    # Client is only needed when actually transcribing
    client = None if (dry_run or only_download) else anthropic.Anthropic(api_key=anthropic_key())
    prefs = SyncPrefs()
    result = PipelineResult()

    # Build the search index inline so a sync also indexes each note as it finalizes
    note_index = None
    if index_path is not None and not (dry_run or only_download):
        from mdnotes.index import NoteIndex
        note_index = NoteIndex(Path(index_path))

    if dry_run:
        print("(dry run — nothing will be downloaded or transcribed)\n")
    if only_download:
        print("(download only — checking per-page cache, no transcription)\n")

    if root_id is None:
        root_id = find_goodnotes_folder_id(service, folder_name=folder_name)

    # List top-level contents and walk them
    subfolders, pdfs = list_items(service, root_id)

    for sub in subfolders:
        if should_stop and should_stop():
            return result
        _sync_folder(
            service, sub["id"], sub["name"], output_dir,
            cache, client, prefs, result, dpi,
            dry_run=dry_run, only_download=only_download,
            folder_path=f"{folder_name} / {sub['name']}",
            assume_yes=assume_yes, note_index=note_index, root_output=output_dir,
            exclude=exclude, interactive=interactive, default_choice=default_choice,
            progress=progress, should_stop=should_stop,
        )

    # PDFs sitting directly in the root (not in a subfolder)
    for pdf in pdfs:
        if should_stop and should_stop():
            return result
        name = pdf["name"]
        stem = Path(name).stem
        md_path = output_dir / f"{stem}.md"
        if _is_up_to_date(pdf, md_path):
            print(f"'{name}' — up-to-date, skipping")
            result.skipped.append(name)
            continue
        if interactive and not assume_yes:
            answer = input(f"Sync '{name}'? [y/N] ").strip().lower()
            if answer != "y":
                print(f"Skipping '{name}'")
                result.skipped.append(name)
                continue
        if dry_run:
            print(f"'{name}' — would sync")
            result.processed.append(name)
        else:
            _sync_file(service, pdf, output_dir, cache, client, result, dpi, indent="",
                       only_download=only_download, note_index=note_index, root_output=output_dir,
                       progress=progress, should_stop=should_stop)

    return result
