# src/mdnotes/pipeline.py
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import anthropic

from mdnotes.cache import TranscriptionCache
from mdnotes.drive import find_goodnotes_folder_id, list_items, download_pdf
from mdnotes.prefs import SyncPrefs, YES, NO
import tempfile
from mdnotes.rasterize import pdf_page_count, pdf_page_hash, rasterize_page
from mdnotes.transcribe import transcribe_page

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
    """Return True if local .md is newer than the Drive file's modifiedTime."""
    if not md_path.exists():
        return False
    drive_mtime = _drive_mtime(file_meta["modifiedTime"])
    local_mtime = datetime.fromtimestamp(md_path.stat().st_mtime, tz=timezone.utc)
    return local_mtime > drive_mtime


def _ask_folder(name: str, indent: str, folder_id: str, prefs: SyncPrefs) -> str:
    """
    Ask what to do with a folder. Returns "yes", "no", or "select".
    Checks stored preferences first; if remembered, uses that without prompting.
    """
    stored = prefs.get(folder_id)
    if stored == YES:
        print(f"{indent}Folder '{name}' → syncing all (remembered)")
        return YES
    if stored == NO:
        print(f"{indent}Folder '{name}' → skipping (remembered)")
        return NO

    while True:
        raw = input(f"{indent}Folder '{name}'? [y]es / [n]o / [s]elect / [Y]es+remember / [N]o+remember: ").strip()
        if raw == "y":
            return YES
        if raw == "n":
            return NO
        if raw == "s":
            return "select"
        if raw == "Y":
            prefs.set(folder_id, YES, name=name)
            print(f"{indent}  (remembered: always sync '{name}')")
            return YES
        if raw == "N":
            prefs.set(folder_id, NO, name=name)
            print(f"{indent}  (remembered: always skip '{name}')")
            return NO


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

    # In only_download mode, download to a temp dir so we don't create real output dirs
    download_dir = Path(tempfile.mkdtemp()) if only_download else output_dir

    try:
        print(f"{indent}  Downloading '{name}'...")
        pdf_path = download_pdf(service, file_id=file_meta["id"], file_name=name, output_dir=download_dir)

        total = pdf_page_count(pdf_path)
        print(f"{indent}  {total} page{'s' if total != 1 else ''}:")

        parts = []
        uncached = 0
        for page_num in range(1, total + 1):
            key = pdf_page_hash(pdf_path, page_num)
            cached = cache.get(key)
            if cached is not None:
                print(f"{indent}    Page {page_num}/{total} — cached")
                parts.append(cached)
            else:
                uncached += 1
                if only_download:
                    print(f"{indent}    Page {page_num}/{total} — would transcribe")
                else:
                    print(f"{indent}    Page {page_num}/{total} — transcribing...")
                    img = rasterize_page(pdf_path, page_num, dpi=dpi)
                    md = transcribe_page(img, cache=cache, client=client, cache_key=key)
                    parts.append(md)

        pdf_path.unlink(missing_ok=True)  # clean up downloaded PDF

        if only_download:
            if uncached:
                print(f"{indent}  {uncached} page{'s' if uncached != 1 else ''} would be transcribed")
                result.processed.append(name)
            else:
                print(f"{indent}  All pages cached — nothing to transcribe")
                result.skipped.append(name)
        else:
            markdown = "\n\n---\n\n".join(parts)
            md_path.write_text(markdown)
            result.processed.append(name)
            print(f"{indent}  Done → {md_path}")
    except Exception as exc:
        print(f"{indent}  Error: {exc}")
        result.errors.append(f"{name}: {exc}")


def _sync_folder(service, folder_id: str, folder_name: str, output_dir: Path,
                 cache: TranscriptionCache, client: anthropic.Anthropic,
                 prefs: SyncPrefs, result: PipelineResult, dpi: int,
                 indent: str = "", mode: str | None = None,
                 dry_run: bool = False, only_download: bool = False) -> None:
    """
    Recursively sync a Drive folder.
    mode: "yes" = sync all without asking, "no" = skip all, None = ask
    dry_run: prompts work normally but nothing is downloaded or transcribed
    only_download: download and check per-page cache but skip transcription
    """
    subfolders, pdfs = list_items(service, folder_id)

    if mode is None:
        if not subfolders and not pdfs:
            print(f"{indent}Folder '{folder_name}' is empty, skipping")
            return
        mode = _ask_folder(folder_name, indent, folder_id, prefs)

    if mode == NO:
        result.skipped.append(folder_name)
        return

    folder_output = output_dir / folder_name
    if not dry_run and not only_download:
        folder_output.mkdir(parents=True, exist_ok=True)

    # Recurse into subfolders
    for sub in subfolders:
        _sync_folder(
            service, sub["id"], sub["name"], folder_output,
            cache, client, prefs, result, dpi,
            indent=indent + "  ",
            mode=mode if mode == YES else None,  # propagate "yes" but re-ask in "select" mode
            dry_run=dry_run, only_download=only_download,
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
    client = anthropic.Anthropic()
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
