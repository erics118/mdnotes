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
