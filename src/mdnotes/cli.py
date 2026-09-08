# src/mdnotes/cli.py
from datetime import datetime, timezone
from pathlib import Path
import click
from mdnotes.auth import get_drive_service
from mdnotes.pipeline import run_pipeline, DEFAULT_CACHE
from mdnotes.prefs import SyncPrefs, CHOICE_LABELS
from mdnotes.config import DEFAULT_NOTES
from mdnotes.index import NoteIndex, DEFAULT_INDEX
from mdnotes.notefmt import TEXTBOOK, build_note, page_block, parse_pages, source_type as detect_source_type
from mdnotes.search import search as run_search
from mdnotes.textbook import extract_pdf_pages

DEFAULT_DPI = 200


@click.group()
def main():
    """mdnotes — sync GoodNotes PDFs from Drive and transcribe to Markdown."""


@main.command()
@click.option("--output-dir", default=None,
              help="Directory to write .md files into. Saved after first use.")
@click.option("--folder-name", default=None,
              help="Name of the GoodNotes folder in Google Drive. Saved after first use.")
@click.option("--dpi", default=None, type=int,
              help=f"Rasterization DPI (higher = better quality, more tokens). Saved after first use. Default: {DEFAULT_DPI}.")
@click.option("--cache", default=str(DEFAULT_CACHE), show_default=True,
              help="Path to transcription cache JSON.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show what would be synced without downloading or transcribing.")
@click.option("--only-download", is_flag=True, default=False,
              help="Download and check per-page cache but skip transcription.")
@click.option("--no-prompt", is_flag=True, default=False,
              help="Sync every folder and file without prompting (grab everything).")
@click.option("--index-path", default=str(DEFAULT_INDEX), show_default=True,
              help="Search index to update as notes are transcribed.")
@click.option("--no-index", is_flag=True, default=False,
              help="Skip updating the search index during sync.")
@click.option("--exclude", multiple=True,
              help="Folder name to skip (repeatable), e.g. --exclude 'CS 3110'.")
def sync(output_dir, folder_name, dpi, cache, dry_run, only_download,
         no_prompt, index_path, no_index, exclude):
    """Download PDFs from Google Drive and transcribe handwriting to Markdown."""
    p = SyncPrefs()

    # Read saved settings once
    saved_folder = p.get_setting("folder_name")
    saved_output = p.get_setting("output_dir")
    saved_dpi    = p.get_setting("dpi")

    # Resolve folder_name: CLI flag > saved pref > error
    if folder_name is None:
        folder_name = saved_folder
    if folder_name is None:
        raise click.UsageError(
            "No folder name configured. Pass --folder-name on first run to save it."
        )

    # Resolve output_dir: CLI flag > saved pref > default
    if output_dir is None:
        output_dir = saved_output or str(DEFAULT_NOTES)

    # Resolve dpi: CLI flag > saved pref > default
    if dpi is None:
        dpi = int(saved_dpi) if saved_dpi is not None else DEFAULT_DPI

    # Persist any newly provided values
    if folder_name and folder_name != saved_folder:
        p.set_setting("folder_name", folder_name)
    if output_dir and output_dir != saved_output:
        p.set_setting("output_dir", output_dir)
    if dpi and str(dpi) != saved_dpi:
        p.set_setting("dpi", str(dpi))

    click.echo(f"folder: {folder_name}  |  output: {output_dir}  |  DPI: {dpi}\n")

    service = get_drive_service()
    result = run_pipeline(
        service=service,
        output_dir=Path(output_dir),
        folder_name=folder_name,
        cache_path=Path(cache),
        dpi=dpi,
        dry_run=dry_run,
        only_download=only_download,
        assume_yes=no_prompt,
        index_path=None if no_index else Path(index_path),
        exclude=set(exclude),
    )

    if result.processed:
        click.echo(f"Transcribed: {', '.join(result.processed)}")
    if result.skipped:
        click.echo(f"Skipped (up-to-date): {', '.join(result.skipped)}")
    if result.errors:
        click.echo("Errors:", err=True)
        for e in result.errors:
            click.echo(f"  {e}", err=True)


@main.command(name="index")
@click.option("--output-dir", default=None,
              help="Directory of .md notes to index. Defaults to saved output-dir or ~/notes.")
@click.option("--index-path", default=str(DEFAULT_INDEX), show_default=True,
              help="Path to the SQLite search index.")
@click.option("--rebuild", is_flag=True, default=False,
              help="Backfill the index from all existing .md files.")
def index_cmd(output_dir, index_path, rebuild):
    """Build or refresh the search index from transcribed .md notes."""
    p = SyncPrefs()
    if output_dir is None:
        output_dir = p.get_setting("output_dir") or str(DEFAULT_NOTES)
    out = Path(output_dir)
    idx = NoteIndex(Path(index_path))

    count = 0
    for md in sorted(out.rglob("*.md")):
        text = md.read_text()
        # skip interrupted syncs (new frontmatter status or legacy marker)
        if "status: in_progress" in text or "<!-- mdnotes: in progress" in text:
            continue
        pages = parse_pages(text)
        if not pages:
            continue
        note_id = md.relative_to(out).as_posix()
        idx.upsert_note(note_id, title=md.stem, pages=pages,
                        path=str(md), source_type=detect_source_type(text))
        count += 1
        click.echo(f"indexed {note_id} ({len(pages)} pages)")
    click.echo(f"\nindexed {count} notes -> {index_path}")


@main.command(name="search")
@click.argument("query")
@click.option("-k", "top_k", default=10, show_default=True, help="Number of results.")
@click.option("--index-path", default=str(DEFAULT_INDEX), show_default=True,
              help="Path to the SQLite search index.")
def search_cmd(query, top_k, index_path):
    """Search transcribed notes (hybrid semantic + full-text)."""
    idx = NoteIndex(Path(index_path))
    hits = run_search(idx, query, k=top_k)
    if not hits:
        click.echo("No results.")
        return
    for h in hits:
        click.echo(f"[{h.score:.3f}] {h.title} (p{h.page_num}) [{h.source_type}]")
        click.echo(f"    {h.snippet}\n")


@main.command(name="ingest-pdf")
@click.argument("pdf_path", type=click.Path(exists=True))
@click.option("--type", "source_type", default=TEXTBOOK, show_default=True,
              help="Source type label stored with the note.")
@click.option("--output-dir", default=None,
              help="Directory to write the extracted .md into.")
@click.option("--index-path", default=str(DEFAULT_INDEX), show_default=True,
              help="Path to the SQLite search index.")
def ingest_pdf_cmd(pdf_path, source_type, output_dir, index_path):
    """Ingest a printed PDF (e.g. a textbook) via its text layer into the search index."""
    p = SyncPrefs()
    if output_dir is None:
        output_dir = p.get_setting("output_dir") or str(DEFAULT_NOTES)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    pdf = Path(pdf_path)
    pages = extract_pdf_pages(pdf)
    if not pages:
        click.echo("No extractable text layer found; this PDF may be scanned images.")
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    blocks = [page_block(pg["page_num"], pg["total"], pg["markdown"]) for pg in pages]
    md_text = build_note({"source_type": source_type, "synced": now}, blocks)
    md_path = out / f"{pdf.stem}.md"
    md_path.write_text(md_text)

    idx = NoteIndex(Path(index_path))
    idx.upsert_note(md_path.relative_to(out).as_posix(), title=pdf.stem, pages=pages,
                    path=str(md_path), source_type=source_type)
    click.echo(f"ingested {pdf.name}: {len(pages)} pages -> {md_path}")


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8000, show_default=True, type=int)
@click.option("--index-path", default=str(DEFAULT_INDEX), show_default=True,
              help="Path to the SQLite search index to serve.")
def serve(host, port, index_path):
    """Run the search web server (FastAPI)."""
    import os
    import uvicorn
    os.environ["MDNOTES_INDEX"] = index_path
    uvicorn.run("mdnotes.server:app", host=host, port=port)


@main.command()
def prefs():
    """View and edit remembered folder sync preferences."""
    p = SyncPrefs()

    while True:
        entries = p.all()

        click.echo("")

        # Show saved settings at the top
        folder_name = p.get_setting("folder_name")
        output_dir = p.get_setting("output_dir")
        dpi = p.get_setting("dpi")
        if folder_name or output_dir or dpi:
            click.echo("Saved settings:\n")
            if folder_name:
                click.echo(f"  folder-name  =  {folder_name}")
            if output_dir:
                click.echo(f"  output-dir   =  {output_dir}")
            if dpi:
                click.echo(f"  dpi          =  {dpi}")
            click.echo("")

        if not entries:
            click.echo("No saved folder preferences.")
        else:
            click.echo("Saved folder preferences:\n")
            for i, (fid, name, choice) in enumerate(entries, 1):
                label = CHOICE_LABELS.get(choice, choice)
                click.echo(f"  {i}. {name}  →  {label}")

        click.echo("")
        click.echo("  [number]        clear a folder preference")
        click.echo("  [f]             edit folder-name")
        click.echo("  [o]             edit output-dir")
        click.echo("  [d]             edit dpi")
        click.echo("  [a]             reset all")
        click.echo("  [q]             quit")
        click.echo("")

        raw = input("Choice: ").strip().lower()

        if raw == "q" or raw == "":
            break
        elif raw == "f":
            current = p.get_setting("folder_name") or ""
            val = input(f"folder-name [{current}]: ").strip()
            if val:
                p.set_setting("folder_name", val)
                click.echo(f"  folder-name set to '{val}'.")
        elif raw == "o":
            current = p.get_setting("output_dir") or ""
            val = input(f"output-dir [{current}]: ").strip()
            if val:
                p.set_setting("output_dir", val)
                click.echo(f"  output-dir set to '{val}'.")
        elif raw == "d":
            current = p.get_setting("dpi") or ""
            val = input(f"dpi [{current}]: ").strip()
            if val:
                if not val.isdigit():
                    click.echo("  DPI must be a number.")
                else:
                    p.set_setting("dpi", val)
                    click.echo(f"  dpi set to {val}.")
        elif raw == "a":
            if input("Reset all preferences? [y/N] ").strip().lower() == "y":
                p.reset()
                click.echo("All preferences cleared.")
        elif raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(entries):
                fid, name, choice = entries[idx]
                p.clear(fid)
                click.echo(f"Cleared preference for '{name}'.")
            else:
                click.echo("Invalid number.")
