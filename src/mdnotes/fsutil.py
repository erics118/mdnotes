import json
import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str, mode: int | None = None) -> None:
    """Write text durably: temp file in the same dir, fsync, then atomic os.replace.

    A crash mid-write leaves the previous file intact instead of a truncated one.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        if mode is not None:
            os.chmod(tmp, mode)
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: Path, default):
    """Load JSON, returning default if the file is missing or unreadable/corrupt."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, ValueError):
        return default


def safe_component(name: str) -> str:
    """Reduce an untrusted name to a single safe path component.

    Replaces separators, strips a leading dot, and rejects traversal so a
    Drive-supplied name can never escape the notes directory.
    """
    cleaned = name.replace("/", "_").replace("\\", "_").replace("\x00", "")
    cleaned = cleaned.lstrip(".").strip()
    if cleaned in ("", ".", ".."):
        return "_"
    return cleaned
