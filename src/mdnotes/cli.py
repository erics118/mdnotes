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
