import base64
from unittest.mock import MagicMock, patch
import pytest
from mdnotes.transcribe import transcribe_page, transcribe_pdf_pages
from mdnotes.cache import TranscriptionCache


FAKE_IMAGE = b"\xff\xd8\xff" + b"\x00" * 100  # minimal JPEG-like bytes


def _make_cache(tmp_path):
    return TranscriptionCache(tmp_path / "cache.json")


def test_transcribe_page_calls_claude(tmp_path):
    """transcribe_page should call the Anthropic API and return the text."""
    cache = _make_cache(tmp_path)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="# My Notes\n- item 1")]
    )

    result = transcribe_page(FAKE_IMAGE, cache=cache, client=mock_client)

    assert result == "# My Notes\n- item 1"
    mock_client.messages.create.assert_called_once()


def test_transcribe_page_uses_cache_on_second_call(tmp_path):
    """Second call with same image bytes should not call the API."""
    cache = _make_cache(tmp_path)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="cached markdown")]
    )

    # First call — populates cache
    transcribe_page(FAKE_IMAGE, cache=cache, client=mock_client)
    # Second call — should be a cache hit
    result = transcribe_page(FAKE_IMAGE, cache=cache, client=mock_client)

    assert result == "cached markdown"
    assert mock_client.messages.create.call_count == 1  # only called once


def test_transcribe_pdf_pages_stitches_pages(tmp_path):
    """transcribe_pdf_pages should join page markdowns with a separator."""
    cache = _make_cache(tmp_path)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="page content")]
    )

    pages = [(1, FAKE_IMAGE), (2, FAKE_IMAGE + b"\x01")]
    result = transcribe_pdf_pages(pages, cache=cache, client=mock_client)

    assert "---" in result
    assert result.count("page content") == 2
