import json
from pathlib import Path
import pytest
from mdnotes.cache import TranscriptionCache


def test_cache_miss_returns_none(tmp_path):
    cache = TranscriptionCache(tmp_path / "cache.json")
    assert cache.get("deadbeef") is None


def test_cache_set_and_get(tmp_path):
    cache = TranscriptionCache(tmp_path / "cache.json")
    cache.set("deadbeef", "# My Notes\n- item")
    assert cache.get("deadbeef") == "# My Notes\n- item"


def test_cache_persists_to_disk(tmp_path):
    path = tmp_path / "cache.json"
    cache1 = TranscriptionCache(path)
    cache1.set("abc123", "some markdown")

    cache2 = TranscriptionCache(path)  # reload from disk
    assert cache2.get("abc123") == "some markdown"


def test_cache_page_hash_is_sha256_of_bytes():
    from mdnotes.cache import page_hash
    data = b"fake image bytes"
    h = page_hash(data)
    import hashlib
    assert h == hashlib.sha256(data).hexdigest()
