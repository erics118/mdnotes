# src/mdnotes/prefs.py
import json
from pathlib import Path

from mdnotes.fsutil import atomic_write_text, read_json

DEFAULT_PREFS = Path.home() / ".config" / "mdnotes" / "prefs.json"

# Stored preference values for a folder
YES = "yes"       # always sync without asking
NO = "no"         # always skip without asking
SELECT = "select" # always enter select mode without asking
# absence of a key = always ask

CHOICE_LABELS = {YES: "always sync", NO: "always skip", SELECT: "always select"}


_SETTINGS_KEY = "__settings__"


class SyncPrefs:
    def __init__(self, path: Path = DEFAULT_PREFS):
        self._path = Path(path)
        # Format: {folder_id: {"choice": "yes"/"no"/"select", "name": "Full / Path"}}
        # Migrates transparently from old flat format {folder_id: "yes"/"no"}
        # Settings stored under reserved key __settings__: {"folder_name": ..., "output_dir": ...}
        self._data: dict[str, dict] = {}
        # a corrupt/partial file must not 500 every endpoint that reads prefs
        raw = read_json(self._path, {})
        if raw:
            for k, v in raw.items():
                if isinstance(v, str):
                    # migrate old format
                    self._data[k] = {"choice": v, "name": k}
                else:
                    self._data[k] = v

    def get(self, folder_id: str) -> str | None:
        """Return stored choice for folder_id ("yes"/"no"/"select"), or None if not set."""
        entry = self._data.get(folder_id)
        return entry["choice"] if entry else None

    def set(self, folder_id: str, value: str, name: str = "") -> None:
        """Store sync preference for folder_id with its full display path."""
        self._data[folder_id] = {"choice": value, "name": name or folder_id}
        self._save()

    def get_setting(self, key: str) -> str | None:
        """Return a named setting (e.g. 'folder_name', 'output_dir'), or None."""
        return self._data.get(_SETTINGS_KEY, {}).get(key)

    def set_setting(self, key: str, value: str) -> None:
        """Persist a named setting."""
        if _SETTINGS_KEY not in self._data:
            self._data[_SETTINGS_KEY] = {}
        self._data[_SETTINGS_KEY][key] = value
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
        """Return list of (folder_id, name, choice) sorted by name, excluding settings."""
        return sorted(
            [(fid, entry["name"], entry["choice"])
             for fid, entry in self._data.items()
             if fid != _SETTINGS_KEY],
            key=lambda x: x[1].lower(),
        )

    def _save(self) -> None:
        atomic_write_text(self._path, json.dumps(self._data, indent=2))
