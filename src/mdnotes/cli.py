# src/mdnotes/cli.py
from pathlib import Path
import click
from mdnotes.auth import get_drive_service
from mdnotes.pipeline import run_pipeline, DEFAULT_CACHE
from mdnotes.prefs import SyncPrefs, CHOICE_LABELS


@click.group()
def main():
    """mdnotes — sync GoodNotes PDFs from Drive and transcribe to Markdown."""


@main.command()
@click.option("--output-dir", default=str(Path.home() / "notes"), show_default=True,
              help="Directory to write .md files into.")
@click.option("--folder-name", required=True,
              help="Name of the GoodNotes folder in Google Drive.")
@click.option("--dpi", default=150, show_default=True,
              help="Rasterization DPI (higher = better quality, more tokens).")
@click.option("--cache", default=str(DEFAULT_CACHE), show_default=True,
              help="Path to transcription cache JSON.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show what would be synced without downloading or transcribing.")
def sync(output_dir, folder_name, dpi, cache, dry_run):
    """Download PDFs from Google Drive and transcribe handwriting to Markdown."""
    service = get_drive_service()
    result = run_pipeline(
        service=service,
        output_dir=Path(output_dir),
        folder_name=folder_name,
        cache_path=Path(cache),
        dpi=dpi,
        dry_run=dry_run,
    )

    if result.processed:
        click.echo(f"Transcribed: {', '.join(result.processed)}")
    if result.skipped:
        click.echo(f"Skipped (up-to-date): {', '.join(result.skipped)}")
    if result.errors:
        click.echo("Errors:", err=True)
        for e in result.errors:
            click.echo(f"  {e}", err=True)


@main.command()
def prefs():
    """View and edit remembered folder sync preferences."""
    p = SyncPrefs()

    while True:
        entries = p.all()

        click.echo("")
        if not entries:
            click.echo("No saved preferences.")
        else:
            click.echo("Saved folder preferences:\n")
            for i, (fid, name, choice) in enumerate(entries, 1):
                label = CHOICE_LABELS.get(choice, choice)
                click.echo(f"  {i}. {name}  →  {label}")

        click.echo("")
        click.echo("  [number] clear a preference")
        click.echo("  [a]      reset all")
        click.echo("  [q]      quit")
        click.echo("")

        raw = input("Choice: ").strip().lower()

        if raw == "q" or raw == "":
            break
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
