# tests/test_auth.py
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from mdnotes.auth import get_drive_service, SCOPES, TOKEN_PATH, CREDS_PATH


def test_scopes_include_drive_readonly():
    assert "https://www.googleapis.com/auth/drive.readonly" in SCOPES


def test_get_drive_service_uses_existing_token(tmp_path, monkeypatch):
    """When a valid token.json exists, it should be loaded without prompting."""
    monkeypatch.setattr("mdnotes.auth.TOKEN_PATH", tmp_path / "token.json")
    monkeypatch.setattr("mdnotes.auth.CREDS_PATH", tmp_path / "client_secret.json")

    mock_creds = MagicMock()
    mock_creds.valid = True

    with patch("mdnotes.auth.Credentials.from_authorized_user_file", return_value=mock_creds) as mock_load, \
         patch("mdnotes.auth.build") as mock_build:
        (tmp_path / "token.json").write_text("{}")
        get_drive_service()
        mock_load.assert_called_once_with(str(tmp_path / "token.json"), SCOPES)
        mock_build.assert_called_once_with("drive", "v3", credentials=mock_creds)


def test_get_drive_service_refreshes_expired_token(tmp_path, monkeypatch):
    """When token is expired but has refresh_token, it should refresh."""
    monkeypatch.setattr("mdnotes.auth.TOKEN_PATH", tmp_path / "token.json")
    monkeypatch.setattr("mdnotes.auth.CREDS_PATH", tmp_path / "client_secret.json")

    mock_creds = MagicMock()
    mock_creds.valid = False
    mock_creds.expired = True
    mock_creds.refresh_token = "some-token"
    mock_creds.to_json.return_value = "{}"

    with patch("mdnotes.auth.Credentials.from_authorized_user_file", return_value=mock_creds), \
         patch("mdnotes.auth.Request") as mock_request, \
         patch("mdnotes.auth.build"):
        (tmp_path / "token.json").write_text("{}")
        get_drive_service()
        mock_creds.refresh.assert_called_once_with(mock_request())
