import hashlib
import json
from pathlib import Path

from mdnotes.fsutil import atomic_write_text, read_json


def page_hash(image_bytes: bytes) -> str:
    """Return SHA-256 hex digest of image bytes."""
    return hashlib.sha256(image_bytes).hexdigest()


class TranscriptionCache:
    def __init__(self, path: Path):
        self._path = Path(path)
        # a truncated cache from an interrupted write must not crash every future sync
        self._data: dict[str, str] = read_json(self._path, {})

    def get(self, hash_: str) -> str | None:
        return self._data.get(hash_)

    def set(self, hash_: str, markdown: str) -> None:
        self._data[hash_] = markdown
        atomic_write_text(self._path, json.dumps(self._data, indent=2))
