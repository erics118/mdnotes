from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from mdnotes.fsutil import atomic_write_text

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_BASE = Path(__file__).parent.parent.parent  # repo root
TOKEN_PATH = _BASE / "credentials" / "token.json"
CREDS_PATH = _BASE / "credentials" / "client_secret.json"


def get_drive_service():
    """Return an authenticated Google Drive v3 service object."""
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        refreshed = False
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                refreshed = True
            except Exception:
                # refresh token revoked/expired -> fall back to a fresh browser login
                creds = None
        if not refreshed:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        # 0600: the refresh token must not be world-readable
        atomic_write_text(TOKEN_PATH, creds.to_json(), mode=0o600)

    return build("drive", "v3", credentials=creds)
