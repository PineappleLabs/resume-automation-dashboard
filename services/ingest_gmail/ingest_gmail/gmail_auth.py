from __future__ import annotations

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build

from .config import settings

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def authorize() -> None:
    """One-time interactive consent. Opens a local browser; requires a human at the keyboard."""
    if not settings.client_secret_path.exists():
        raise RuntimeError(
            f"No client_secret.json found at {settings.client_secret_path}. "
            "Download it from Google Cloud Console (OAuth client, Desktop app type) first."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(settings.client_secret_path), SCOPES)
    creds = flow.run_local_server(port=0)
    settings.token_path.parent.mkdir(parents=True, exist_ok=True)
    settings.token_path.write_text(creds.to_json(), encoding="utf-8")


def load_credentials() -> Credentials:
    if not settings.token_path.exists():
        raise RuntimeError(
            "No stored Gmail credentials. Run `ingest-gmail authorize` once, interactively, "
            "then re-run."
        )
    creds = Credentials.from_authorized_user_file(str(settings.token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
        settings.token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_gmail_service() -> Resource:
    return build("gmail", "v1", credentials=load_credentials(), cache_discovery=False)
