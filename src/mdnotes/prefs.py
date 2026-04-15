# src/mdnotes/prefs.py
import json
from pathlib import Path

DEFAULT_PREFS = Path.home() / ".config" / "mdnotes" / "prefs.json"

# Stored preference values for a folder
YES = "yes"    # always sync without asking
NO = "no"      # always skip without asking
# absence of a key = always ask


class SyncPrefs:
    def __init__(self, path: Path = DEFAULT_PREFS):
        self._path = Path(path)
        self._data: dict[str, str] = {}
        if self._path.exists():
            self._data = json.loads(self._path.read_text())

    def get(self, folder_id: str) -> str | None:
        """Return stored preference for folder_id, or None if not set."""
        return self._data.get(folder_id)

    def set(self, folder_id: str, value: str) -> None:
        """Store YES or NO preference for folder_id and persist to disk."""
        self._data[folder_id] = value
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))

    def clear(self, folder_id: str) -> None:
        """Remove stored preference for folder_id."""
        if folder_id in self._data:
            del self._data[folder_id]
            self._path.write_text(json.dumps(self._data, indent=2))
