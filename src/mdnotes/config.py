import os


def anthropic_key() -> str | None:
    return os.environ.get("MDNOTES_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")


def voyage_key() -> str | None:
    return os.environ.get("MDNOTES_VOYAGE_API_KEY") or os.environ.get("VOYAGE_API_KEY")
