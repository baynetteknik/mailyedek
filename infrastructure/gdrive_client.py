"""
gdrive_client.py — Google Drive adapter implementing CloudStorageProvider.

Clean Architecture — Infrastructure Layer.
Uses google-api-python-client with OAuth 2.0, supports resumable upload,
exponential backoff, and quota checking.
"""

import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from domain.interfaces import CloudStorageProvider

logger = logging.getLogger(__name__)

RETRY_DELAYS = [5, 15, 30, 60]
MIME_TYPE_ZIP = "application/zip"
MIME_TYPE_MBOX = "application/mbox"
MIME_TYPE_FOLDER = "application/vnd.google-apps.folder"
TOKEN_FILE = Path("data/gdrive_token.json")
CREDENTIALS_FILE = Path("data/gdrive_credentials.json")


class GoogleDriveClient(CloudStorageProvider):
    """Google Drive storage provider with OAuth 2.0 and resumable upload."""

    def __init__(self, credentials_path: Optional[Path] = None,
                 token_path: Optional[Path] = None):
        self._credentials_path = credentials_path or CREDENTIALS_FILE
        self._token_path = token_path or TOKEN_FILE
        self._service: Any = None

    # ------------------------------------------------------------------
    # Connection / Auth
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Authenticate with Google Drive using OAuth 2.0."""
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            SCOPES = ["https://www.googleapis.com/auth/drive.file"]

            creds = None

            # Load existing token
            if self._token_path.exists():
                creds = Credentials.from_authorized_user_file(str(self._token_path), SCOPES)

            # Refresh if expired
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())

            # Auth flow if needed
            if not creds or not creds.valid:
                if not self._credentials_path.exists():
                    logger.error(
                        "Google Drive credentials not found at %s. "
                        "Download from Google Cloud Console.",
                        self._credentials_path
                    )
                    return False
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)
                # Save token
                self._token_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._token_path, "w") as f:
                    f.write(creds.to_json())

            self._service = build("drive", "v3", credentials=creds)
            logger.info("Google Drive authenticated successfully")
            return True

        except ImportError:
            logger.error(
                "Google API libraries not installed. "
                "Install with: pip install google-api-python-client google-auth-oauthlib"
            )
            return False
        except Exception as exc:
            logger.error("Google Drive auth failed: %s", exc)
            return False

    def is_connected(self) -> bool:
        if not self._service:
            return False
        try:
            self._service.about().get(fields="user").execute()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload(self, local_path: Path, remote_key: str) -> bool:
        """Upload a file to Google Drive with retry logic."""
        if not self._service:
            return False

        if not local_path.exists():
            logger.error("File not found: %s", local_path)
            return False

        # Determine MIME type
        mime_type = MIME_TYPE_ZIP
        if local_path.suffix.lower() == ".mbox":
            mime_type = MIME_TYPE_MBOX

        file_metadata = {"name": remote_key}

        for attempt, delay in enumerate(RETRY_DELAYS + [60]):
            try:
                from googleapiclient.http import MediaFileUpload

                media = MediaFileUpload(
                    str(local_path),
                    mimetype=mime_type,
                    resumable=True,
                    chunksize=10 * 1024 * 1024,  # 10 MB chunks
                )

                request = self._service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields="id, name, size",
                )

                response = None
                while response is None:
                    status, response = request.next_chunk()
                    if status:
                        pct = int(status.progress() * 100)
                        if pct % 20 == 0:
                            logger.debug("Upload progress: %d%%", pct)

                logger.info("Uploaded %s → Drive (file ID: %s)", local_path.name, response.get("id"))
                return True

            except Exception as exc:
                logger.warning("GDrive upload attempt %d failed: %s", attempt + 1, exc)
                if attempt < len(RETRY_DELAYS):
                    time.sleep(delay)

        return False

    def upload_stream(self, stream: Generator[bytes, None, None],
                      remote_key: str, content_length: int) -> bool:
        """Stream-upload to Google Drive.

        TODO: Implement using MediaIoBaseUpload for streaming.
        """
        raise NotImplementedError("Streaming upload to GDrive is not yet implemented.")

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download(self, remote_key: str, local_path: Path) -> bool:
        """Download a file from Google Drive by filename."""
        if not self._service:
            return False

        for attempt, delay in enumerate(RETRY_DELAYS + [60]):
            try:
                # Find file by name
                query = f"name = '{remote_key}' and trashed = false"
                results = self._service.files().list(
                    q=query, fields="files(id, name, size)"
                ).execute()
                files = results.get("files", [])
                if not files:
                    logger.error("File not found in Drive: %s", remote_key)
                    return False

                file_id = files[0]["id"]

                from googleapiclient.http import MediaIoBaseDownload

                request = self._service.files().get_media(fileId=file_id)
                with open(local_path, "wb") as f:
                    downloader = MediaIoBaseDownload(f, request)
                    done = False
                    while not done:
                        status, done = downloader.next_chunk()
                        if status:
                            pct = int(status.progress() * 100)
                            logger.debug("Download progress: %d%%", pct)

                logger.info("Downloaded %s → %s", remote_key, local_path)
                return True

            except Exception as exc:
                logger.warning("GDrive download attempt %d failed: %s", attempt + 1, exc)
                if attempt < len(RETRY_DELAYS):
                    time.sleep(delay)

        return False

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def list_files(self, prefix: str = "") -> List[Dict[str, Any]]:
        if not self._service:
            return []
        try:
            query = f"name contains '{prefix}' and trashed = false" if prefix else "trashed = false"
            results: List[Dict[str, Any]] = []
            page_token = None
            while True:
                response = self._service.files().list(
                    q=query,
                    fields="files(id, name, size, mimeType, createdTime)",
                    pageToken=page_token,
                ).execute()
                for f in response.get("files", []):
                    results.append({
                        "id": f["id"],
                        "name": f["name"],
                        "size": int(f.get("size", 0)),
                        "mime_type": f.get("mimeType", ""),
                        "created_at": f.get("createdTime", ""),
                    })
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
            return results
        except Exception as exc:
            logger.error("Error listing Drive files: %s", exc)
            return []

    def delete_file(self, remote_key: str) -> bool:
        if not self._service:
            return False
        try:
            query = f"name = '{remote_key}' and trashed = false"
            results = self._service.files().list(q=query, fields="files(id)").execute()
            for f in results.get("files", []):
                self._service.files().delete(fileId=f["id"]).execute()
            return True
        except Exception as exc:
            logger.error("Error deleting Drive file: %s", exc)
            return False

    def file_exists(self, remote_key: str) -> bool:
        if not self._service:
            return False
        try:
            query = f"name = '{remote_key}' and trashed = false"
            results = self._service.files().list(q=query, fields="files(id)").execute()
            return len(results.get("files", [])) > 0
        except Exception:
            return False

    def get_quota(self) -> Dict[str, Any]:
        if not self._service:
            return {}
        try:
            about = self._service.about().get(fields="storageQuota").execute()
            quota = about.get("storageQuota", {})
            return {
                "total_bytes": int(quota.get("limit", 0)),
                "used_bytes": int(quota.get("usage", 0)),
                "free_bytes": int(quota.get("limit", 0)) - int(quota.get("usage", 0)),
            }
        except Exception as exc:
            logger.error("Error getting Drive quota: %s", exc)
            return {}
