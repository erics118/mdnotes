# tests/test_prefs.py
import json
import pytest
from mdnotes.prefs import SyncPrefs, YES, NO, SELECT


def _prefs(tmp_path):
    return SyncPrefs(tmp_path / "prefs.json")


# --- get / set / clear / reset ---

def test_missing_file_initializes_empty(tmp_path):
    p = _prefs(tmp_path)
    assert p.get("folder1") is None


def test_set_and_get(tmp_path):
    p = _prefs(tmp_path)
    p.set("f1", YES, name="GoodNotes / Math")
    assert p.get("f1") == YES


def test_get_unknown_returns_none(tmp_path):
    p = _prefs(tmp_path)
    p.set("f1", YES)
    assert p.get("f2") is None


def test_persists_to_disk(tmp_path):
    path = tmp_path / "prefs.json"
    p = SyncPrefs(path)
    p.set("f1", NO, name="My Folder")
    p2 = SyncPrefs(path)
    assert p2.get("f1") == NO


def test_clear_removes_entry(tmp_path):
    p = _prefs(tmp_path)
    p.set("f1", YES)
    p.clear("f1")
    assert p.get("f1") is None


def test_clear_nonexistent_is_noop(tmp_path):
    p = _prefs(tmp_path)
    p.clear("does-not-exist")  # should not raise


def test_reset_clears_all_folder_prefs(tmp_path):
    p = _prefs(tmp_path)
    p.set("f1", YES)
    p.set("f2", NO)
    p.reset()
    assert p.get("f1") is None
    assert p.get("f2") is None


# --- all() ---

def test_all_returns_sorted_by_name(tmp_path):
    p = _prefs(tmp_path)
    p.set("id_b", YES, name="Zebra")
    p.set("id_a", NO, name="Apple")
    entries = p.all()
    assert [name for _, name, _ in entries] == ["Apple", "Zebra"]


def test_all_excludes_settings_key(tmp_path):
    p = _prefs(tmp_path)
    p.set("f1", YES, name="Math")
    p.set_setting("folder_name", "GoodNotes 5")
    entries = p.all()
    assert len(entries) == 1
    assert entries[0][1] == "Math"


def test_all_empty_when_no_prefs(tmp_path):
    p = _prefs(tmp_path)
    assert p.all() == []


# --- settings ---

def test_get_setting_returns_none_when_unset(tmp_path):
    p = _prefs(tmp_path)
    assert p.get_setting("folder_name") is None


def test_set_and_get_setting(tmp_path):
    p = _prefs(tmp_path)
    p.set_setting("folder_name", "GoodNotes 5")
    assert p.get_setting("folder_name") == "GoodNotes 5"


def test_settings_persist_to_disk(tmp_path):
    path = tmp_path / "prefs.json"
    p = SyncPrefs(path)
    p.set_setting("output_dir", "/home/user/notes")
    p2 = SyncPrefs(path)
    assert p2.get_setting("output_dir") == "/home/user/notes"


def test_multiple_settings_coexist(tmp_path):
    p = _prefs(tmp_path)
    p.set_setting("folder_name", "GoodNotes 5")
    p.set_setting("dpi", "200")
    assert p.get_setting("folder_name") == "GoodNotes 5"
    assert p.get_setting("dpi") == "200"


# --- migration from old flat format ---

def test_migrates_old_flat_format(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"folder123": "yes", "folder456": "no"}))
    p = SyncPrefs(path)
    assert p.get("folder123") == YES
    assert p.get("folder456") == NO


def test_migration_preserves_id_as_name(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"folder123": "select"}))
    p = SyncPrefs(path)
    entries = p.all()
    assert entries[0][0] == "folder123"  # id
    assert entries[0][2] == SELECT
