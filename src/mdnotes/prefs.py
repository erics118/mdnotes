# src/mdnotes/prefs.py
import json
from pathlib import Path

DEFAULT_PREFS = Path.home() / ".config" / "mdnotes" / "prefs.json"

# Stored preference values for a folder
YES = "yes"    # always sync without asking
NO = "no"      # always skip without asking
# absence of a key = always ask

CHOICE_LABELS = {YES: "always sync", NO: "always skip"}


class SyncPrefs:
    def __init__(self, path: Path = DEFAULT_PREFS):
        self._path = Path(path)
        # Format: {folder_id: {"choice": "yes"/"no", "name": "Folder Name"}}
        # Migrates transparently from old flat format {folder_id: "yes"/"no"}
        self._data: dict[str, dict] = {}
        if self._path.exists():
            raw = json.loads(self._path.read_text())
            for k, v in raw.items():
                if isinstance(v, str):
                    # migrate old format
                    self._data[k] = {"choice": v, "name": k}
                else:
                    self._data[k] = v

    def get(self, folder_id: str) -> str | None:
        """Return stored choice for folder_id ("yes"/"no"), or None if not set."""
        entry = self._data.get(folder_id)
        return entry["choice"] if entry else None

    def set(self, folder_id: str, value: str, name: str = "") -> None:
        """Store YES or NO preference for folder_id with its display name."""
        self._data[folder_id] = {"choice": value, "name": name or folder_id}
        self._save()

    def clear(self, folder_id: str) -> None:
        """Remove stored preference for folder_id."""
        if folder_id in self._data:
            del self._data[folder_id]
            self._save()

    def reset(self) -> None:
        """Remove all stored preferences."""
        self._data = {}
        self._save()

    def all(self) -> list[tuple[str, str, str]]:
        """Return list of (folder_id, name, choice) sorted by name."""
        return sorted(
            [(fid, entry["name"], entry["choice"]) for fid, entry in self._data.items()],
            key=lambda x: x[1].lower(),
        )

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))
