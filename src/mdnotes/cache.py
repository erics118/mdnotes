import hashlib
import json
from pathlib import Path


def page_hash(image_bytes: bytes) -> str:
    """Return SHA-256 hex digest of image bytes."""
    return hashlib.sha256(image_bytes).hexdigest()


class TranscriptionCache:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._data: dict[str, str] = {}
        if self._path.exists():
            self._data = json.loads(self._path.read_text())

    def get(self, hash_: str) -> str | None:
        return self._data.get(hash_)

    def set(self, hash_: str, markdown: str) -> None:
        self._data[hash_] = markdown
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))
