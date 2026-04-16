# src/mdnotes/cli.py
from pathlib import Path
import click
from mdnotes.auth import get_drive_service
from mdnotes.pipeline import run_pipeline, DEFAULT_CACHE
from mdnotes.prefs import SyncPrefs, CHOICE_LABELS

DEFAULT_DPI = 150


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
def sync(output_dir, folder_name, dpi, cache, dry_run, only_download):
    """Download PDFs from Google Drive and transcribe handwriting to Markdown."""
    p = SyncPrefs()

    # Resolve folder_name: CLI flag > saved pref > error
    if folder_name is None:
        folder_name = p.get_setting("folder_name")
    if folder_name is None:
        raise click.UsageError(
            "No folder name configured. Pass --folder-name on first run to save it."
        )

    # Resolve output_dir: CLI flag > saved pref > default
    if output_dir is None:
        output_dir = p.get_setting("output_dir") or str(Path.home() / "notes")

    # Resolve dpi: CLI flag > saved pref > default
    if dpi is None:
        saved_dpi = p.get_setting("dpi")
        dpi = int(saved_dpi) if saved_dpi is not None else DEFAULT_DPI

    # Persist any newly provided values
    if folder_name and folder_name != p.get_setting("folder_name"):
        p.set_setting("folder_name", folder_name)
    if output_dir and output_dir != p.get_setting("output_dir"):
        p.set_setting("output_dir", output_dir)
    if dpi and str(dpi) != p.get_setting("dpi"):
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
