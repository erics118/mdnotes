# src/mdnotes/pipeline.py
import re
import tempfile
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import anthropic

from mdnotes.cache import TranscriptionCache
from mdnotes.drive import find_goodnotes_folder_id, list_items, download_pdf
from mdnotes.prefs import SyncPrefs, YES, NO, SELECT
from mdnotes.rasterize import pdf_page_count, pdf_page_hash, rasterize_page
from mdnotes.transcribe import transcribe_page, TRANSCRIBE_VERSION

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


def _is_up_to_date(file_meta: dict, md_path: Path) -> bool:
    """Return True if local .md was synced from the same (or newer) Drive version and is complete."""
    if not md_path.exists():
        return False
    text = md_path.read_text()
    # A file with the in-progress marker was interrupted — always re-sync
    if "<!-- mdnotes: in progress" in text:
        return False
    # Prefer comparing recorded Drive mtime embedded in the file header
    m = re.search(r"<!-- mdnotes: synced: ([^-].*?) -->", text)
    if m:
        recorded = _drive_mtime(m.group(1))
        current = _drive_mtime(file_meta["modifiedTime"])
        return recorded >= current
    # Fallback for files written before the synced-header feature
    drive_mtime = _drive_mtime(file_meta["modifiedTime"])
    local_mtime = datetime.fromtimestamp(md_path.stat().st_mtime, tz=timezone.utc)
    return local_mtime > drive_mtime


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
               only_download: bool = False) -> None:
    """Download, rasterize, transcribe, and save one PDF, page by page with cache.

    only_download: download and check per-page cache but skip transcription and writing.
    """
    name = file_meta["name"]
    stem = Path(name).stem
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
            pdf_path = download_pdf(service, file_id=file_meta["id"], file_name=name, output_dir=download_dir)

            total = pdf_page_count(pdf_path)
            print(f"{indent}  {total} page{'s' if total != 1 else ''}:")

            uncached = 0

            # Recover already-written pages from an interrupted previous run
            pages_done = []
            resume_from = 1
            if not only_download and md_path.exists():
                existing = md_path.read_text()
                if "<!-- mdnotes: in progress" in existing:
                    # Check whether the interrupted run was for the same PDF version
                    m = re.search(r"<!-- mdnotes: in progress: (\S+?) -->", existing)
                    same_version = m and m.group(1) == file_meta["modifiedTime"]
                    if same_version:
                        # Parse out completed page blocks — each starts with <!-- page N/total -->
                        blocks = re.findall(r"<!-- page \d+/\d+ -->\n.*?(?=\n\n---\n\n<!-- page |\n\n<!-- mdnotes|$)",
                                            existing, re.DOTALL)
                        if blocks:
                            pages_done = blocks
                            resume_from = len(blocks) + 1
                            print(f"{indent}  Resuming from page {resume_from}/{total} ({len(blocks)} already written)")
                    else:
                        print(f"{indent}  PDF changed since last interrupted run — starting fresh")

            for page_num in range(1, total + 1):
                if page_num < resume_from:
                    print(f"{indent}    Page {page_num}/{total} — already written")
                    continue

                key = f"{pdf_page_hash(pdf_path, page_num)}:dpi={dpi}:v={TRANSCRIBE_VERSION}"
                cached = cache.get(key)
                if cached is not None:
                    print(f"{indent}    Page {page_num}/{total} — cached")
                    page_md = cached
                else:
                    uncached += 1
                    if only_download:
                        print(f"{indent}    Page {page_num}/{total} — would transcribe")
                        continue
                    else:
                        print(f"{indent}    Page {page_num}/{total} — transcribing...")
                        img = rasterize_page(pdf_path, page_num, dpi=dpi)
                        page_md = transcribe_page(img, cache=cache, client=client, cache_key=key)

                if not only_download:
                    pages_done.append(f"<!-- page {page_num}/{total} -->\n{page_md}")
                    # Rewrite file after each page with marker at end — marker absence = complete
                    # Embed Drive modifiedTime so resume can detect if the PDF changed
                    md_path.write_text(
                        "\n\n---\n\n".join(pages_done)
                        + f"\n\n<!-- mdnotes: in progress: {file_meta['modifiedTime']} -->"
                    )

            # pdf_path lives in _tmp for only_download (cleaned up by context manager);
            # for normal sync, unlink it explicitly
            if not only_download:
                pdf_path.unlink(missing_ok=True)

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
                # Write final file: synced header followed by page blocks, no in-progress marker
                header = f"<!-- mdnotes: synced: {file_meta['modifiedTime']} -->"
                md_path.write_text(header + "\n\n" + "\n\n---\n\n".join(pages_done))
                result.processed.append(name)
                print(f"{indent}  Done → {md_path}")
        except Exception as exc:
            print(f"{indent}  Error: {exc}")
            result.errors.append(f"{name}: {exc}")


def _sync_folder(service, folder_id: str, folder_name: str, output_dir: Path,
                 cache: TranscriptionCache, client: anthropic.Anthropic,
                 prefs: SyncPrefs, result: PipelineResult, dpi: int,
                 indent: str = "", mode: str | None = None,
                 dry_run: bool = False, only_download: bool = False,
                 folder_path: str | None = None) -> None:
    """
    Recursively sync a Drive folder.
    mode: "yes" = sync all without asking, "no" = skip all, None = ask
    dry_run: prompts work normally but nothing is downloaded or transcribed
    only_download: download and check per-page cache but skip transcription
    folder_path: full slash-separated path for display in saved prefs
    """
    full_path = folder_path or folder_name
    subfolders, pdfs = list_items(service, folder_id)

    if mode is None:
        if not subfolders and not pdfs:
            print(f"{indent}Folder '{folder_name}' is empty, skipping")
            return
        mode = _ask_folder(folder_name, indent, folder_id, prefs, full_path=full_path)

    if mode == NO:
        result.skipped.append(folder_name)
        return

    folder_output = output_dir / folder_name
    if not dry_run:
        folder_output.mkdir(parents=True, exist_ok=True)

    # Recurse into subfolders
    for sub in subfolders:
        _sync_folder(
            service, sub["id"], sub["name"], folder_output,
            cache, client, prefs, result, dpi,
            indent=indent + "  ",
            mode=mode if mode == YES else None,  # propagate "yes" but re-ask in "select"/"no" mode
            dry_run=dry_run, only_download=only_download,
            folder_path=f"{full_path} / {sub['name']}",
        )

    # Sync PDFs
    for pdf in pdfs:
        name = pdf["name"]
        stem = Path(name).stem
        md_path = folder_output / f"{stem}.md"

        if mode == "select":
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
                       only_download=only_download)


def run_pipeline(
    service,
    output_dir: Path,
    folder_name: str,
    cache_path: Path = DEFAULT_CACHE,
    dpi: int = 150,
    dry_run: bool = False,
    only_download: bool = False,
) -> PipelineResult:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cache = TranscriptionCache(cache_path)
    # Client is only needed when actually transcribing
    client = None if (dry_run or only_download) else anthropic.Anthropic()
    prefs = SyncPrefs()
    result = PipelineResult()

    if dry_run:
        print("(dry run — nothing will be downloaded or transcribed)\n")
    if only_download:
        print("(download only — checking per-page cache, no transcription)\n")

    root_id = find_goodnotes_folder_id(service, folder_name=folder_name)

    # List top-level contents and walk them
    subfolders, pdfs = list_items(service, root_id)

    for sub in subfolders:
        _sync_folder(
            service, sub["id"], sub["name"], output_dir,
            cache, client, prefs, result, dpi,
            dry_run=dry_run, only_download=only_download,
            folder_path=f"{folder_name} / {sub['name']}",
        )

    # PDFs sitting directly in the root (not in a subfolder)
    for pdf in pdfs:
        name = pdf["name"]
        stem = Path(name).stem
        md_path = output_dir / f"{stem}.md"
        if _is_up_to_date(pdf, md_path):
            print(f"'{name}' — up-to-date, skipping")
            result.skipped.append(name)
            continue
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
                       only_download=only_download)

    return result
