"""
Google Drive upload for the serverless version — authenticates using a
refresh token stored as an env var, instead of the interactive browser
flow (there's no browser to pop up on a server).

One-time setup (do this once, locally, before deploying):
1. You already have token.json from running drive_auth.py locally.
2. Open it and copy the "refresh_token", "client_id", and "client_secret"
   values out of it (or run get_refresh_token.py in this folder, which
   prints them for you).
3. Paste those three values into Vercel's env vars as:
   GOOGLE_OAUTH_REFRESH_TOKEN, GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET
4. Also set GOOGLE_DRIVE_BILLS_FOLDER_ID, same as before.

From then on, every request silently exchanges the refresh token for a
fresh access token — no login screen, ever, until you revoke access.
"""
import io
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
BILLS_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_BILLS_FOLDER_ID")


def get_credentials() -> Credentials:
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_OAUTH_REFRESH_TOKEN"],
        client_id=os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    creds.refresh(Request())  # exchange the refresh token for a live access token
    return creds


def get_service():
    if not BILLS_FOLDER_ID:
        raise RuntimeError("Set GOOGLE_DRIVE_BILLS_FOLDER_ID.")
    return build("drive", "v3", credentials=get_credentials())


def upload_bill_bytes(file_bytes: bytes, filename: str, mimetype: str) -> tuple[str, str]:
    """
    Upload from in-memory bytes rather than a file path — serverless
    functions have no persistent disk to read a saved file back from.
    Returns (drive_file_id, web_view_link).
    """
    service = get_service()
    metadata = {"name": filename, "parents": [BILLS_FOLDER_ID]}
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mimetype, resumable=False)
    uploaded = (
        service.files()
        .create(body=metadata, media_body=media, fields="id, webViewLink")
        .execute()
    )
    return uploaded["id"], uploaded["webViewLink"]
