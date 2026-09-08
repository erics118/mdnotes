import base64
from unittest.mock import MagicMock, patch
import pytest
from mdnotes.transcribe import transcribe_page, TranscribeError
from mdnotes.cache import TranscriptionCache


FAKE_IMAGE = b"\xff\xd8\xff" + b"\x00" * 100  # minimal JPEG-like bytes


def _text_block(text):
    b = MagicMock()
    b.type = "text"
    b.text = text
    return b


def _response(text, stop_reason="end_turn"):
    return MagicMock(content=[_text_block(text)], stop_reason=stop_reason)


def _make_cache(tmp_path):
    return TranscriptionCache(tmp_path / "cache.json")


def test_transcribe_page_calls_claude(tmp_path):
    """transcribe_page should call the Anthropic API and return the text."""
    cache = _make_cache(tmp_path)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _response("# My Notes\n- item 1")

    result = transcribe_page(FAKE_IMAGE, cache=cache, client=mock_client)

    assert result == "# My Notes\n- item 1"
    mock_client.messages.create.assert_called_once()


def test_transcribe_page_rejects_truncated_response(tmp_path):
    """A max_tokens (truncated) response must raise, not be cached as complete."""
    cache = _make_cache(tmp_path)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _response("half a page", stop_reason="max_tokens")

    with pytest.raises(TranscribeError):
        transcribe_page(FAKE_IMAGE, cache=cache, client=mock_client, cache_key="k")
    assert cache.get("k") is None  # nothing cached


def test_transcribe_page_with_explicit_cache_key(tmp_path):
    """When cache_key is given, that key is used instead of hashing image_bytes."""
    cache = _make_cache(tmp_path)
    cache.set("pdf-hash:dpi=150", "pre-cached content")
    mock_client = MagicMock()

    result = transcribe_page(FAKE_IMAGE, cache=cache, client=mock_client, cache_key="pdf-hash:dpi=150")

    assert result == "pre-cached content"
    mock_client.messages.create.assert_not_called()


def test_transcribe_page_uses_cache_on_second_call(tmp_path):
    """Second call with same image bytes should not call the API."""
    cache = _make_cache(tmp_path)
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _response("cached markdown")

    # First call — populates cache
    transcribe_page(FAKE_IMAGE, cache=cache, client=mock_client)
    # Second call — should be a cache hit
    result = transcribe_page(FAKE_IMAGE, cache=cache, client=mock_client)

    assert result == "cached markdown"
    assert mock_client.messages.create.call_count == 1  # only called once


