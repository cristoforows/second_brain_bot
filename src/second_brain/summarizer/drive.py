from __future__ import annotations

import io
import json
import os
import threading
from typing import Any

import structlog
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

log = structlog.get_logger()

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_CLIENT_SECRETS_FILE = "client_secret.json"


def _escape_drive_query(value: str) -> str:
    """Escape a value for safe interpolation into a Drive API query string."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _write_token(token_path: str, creds: Credentials) -> None:
    """Write OAuth credentials to token_path with owner-only permissions (0o600)."""
    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(creds.to_json())


def _load_credentials(token_path: str) -> Credentials:
    """Load OAuth2 credentials.

    Checks GOOGLE_TOKEN_JSON env var first (used in CI/GHA — no file needed).
    Falls back to token_path on disk (used locally).
    If neither exists, runs the interactive OAuth consent flow.
    """
    token_json_env = os.environ.get("GOOGLE_TOKEN_JSON")

    if token_json_env:
        log.info("loading_credentials_from_env")
        creds = Credentials.from_authorized_user_info(json.loads(token_json_env), scopes=_SCOPES)
        from_env = True
    else:
        from_env = False
        token_exists = os.path.isfile(token_path) and os.path.getsize(token_path) > 0
        if token_exists:
            creds = Credentials.from_authorized_user_file(token_path, scopes=_SCOPES)
        else:
            log.info("token_missing_starting_oauth_flow", token_path=token_path)
            if not os.path.isfile(_CLIENT_SECRETS_FILE):
                raise FileNotFoundError(
                    f"'{token_path}' is missing or empty and no '{_CLIENT_SECRETS_FILE}' was found.\n"
                    f"Download your OAuth 2.0 client credentials from Google Cloud Console → "
                    f"APIs & Services → Credentials → Download JSON, and save it as '{_CLIENT_SECRETS_FILE}'."
                )
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(_CLIENT_SECRETS_FILE, _SCOPES)
            creds = flow.run_local_server(port=0)
            _write_token(token_path, creds)
            log.info("token_saved", token_path=token_path)

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            if not from_env:
                _write_token(token_path, creds)
        except RefreshError as e:
            log.warning("token_refresh_failed", error=str(e))
            if not from_env:
                os.remove(token_path)
            raise RuntimeError(
                "OAuth token refresh failed. "
                "Re-authenticate by running the script interactively or updating the GOOGLE_TOKEN_JSON secret."
            ) from e

    return creds


class DriveService:
    """Google Drive CRUD operations via OAuth2 user credentials.

    This is a raw API wrapper with no LangChain awareness.
    """

    def __init__(self, token_path: str) -> None:
        creds = _load_credentials(token_path)
        self._service = build("drive", "v3", credentials=creds)
        # googleapiclient's underlying httplib2.Http holds a single SSL socket
        # that is not thread-safe. LangGraph dispatches parallel tool calls,
        # so we serialize every API call through this lock.
        self._lock = threading.Lock()
        self._reads: list[str] = []
        self._updates: list[str] = []

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def list_files(
        self, folder_id: str, mime_type: str | None = None
    ) -> list[dict[str, Any]]:
        """List files in a folder. Optionally filter by MIME type."""
        query = f"parents='{_escape_drive_query(folder_id)}' and trashed = false"
        if mime_type:
            query += f" and mimeType = '{_escape_drive_query(mime_type)}'"

        results: list[dict[str, Any]] = []
        page_token: str | None = None

        while True:
            try:
                with self._lock:
                    resp = (
                        self._service.files()
                        .list(
                            q=query,
                            fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
                            pageToken=page_token,
                        )
                        .execute()
                    )
            except HttpError as e:
                log.error("drive_list_files_failed", folder_id=folder_id, status=e.status_code, error=str(e))
                raise
            results.extend(resp.get("files", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return results

    def read_file(self, file_id: str, display_path: str) -> str:
        """Download and return the text content of a file.

        ``display_path`` is a human-readable identifier used only for logging.
        """
        try:
            with self._lock:
                content = (
                    self._service.files()
                    .export(fileId=file_id, mimeType="text/plain")
                    .execute()
                )
        except HttpError as e:
            log.error("drive_read_file_failed", file_id=file_id, path=display_path, status=e.status_code, error=str(e))
            raise
        try:
            decoded = content.decode("utf-8") if isinstance(content, bytes) else str(content)
        except UnicodeDecodeError as e:
            log.error("drive_read_file_decode_failed", file_id=file_id, path=display_path, error=str(e))
            raise
        log.info("file_read", path=display_path)
        self._reads.append(display_path)
        return decoded

    def read_file_raw(self, file_id: str, display_path: str) -> str:
        """Download raw file content (for non-Google-Docs files like .md).

        ``display_path`` is a human-readable identifier used only for logging.
        """
        try:
            with self._lock:
                content = self._service.files().get_media(fileId=file_id).execute()
        except HttpError as e:
            log.error("drive_read_file_raw_failed", file_id=file_id, path=display_path, status=e.status_code, error=str(e))
            raise
        try:
            decoded = content.decode("utf-8") if isinstance(content, bytes) else str(content)
        except UnicodeDecodeError as e:
            log.error("drive_read_file_raw_decode_failed", file_id=file_id, path=display_path, error=str(e))
            raise
        log.info("file_read", path=display_path)
        self._reads.append(display_path)
        return decoded

    def find_file(self, folder_id: str, name: str) -> dict[str, Any] | None:
        """Find a file by exact name within a folder. Returns None if not found."""
        query = (
            f"parents='{_escape_drive_query(folder_id)}' "
            f"and name = '{_escape_drive_query(name)}' "
            f"and trashed = false"
        )
        try:
            with self._lock:
                resp = (
                    self._service.files()
                    .list(q=query, fields="files(id, name, mimeType)", pageSize=1)
                    .execute()
                )
        except HttpError as e:
            log.error("drive_find_file_failed", folder_id=folder_id, name=name, status=e.status_code, error=str(e))
            raise
        files = resp.get("files", [])
        return files[0] if files else None

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def write_file(self, folder_id: str, name: str, content: str, display_path: str = "") -> str:
        """Create a new file in the given folder. Returns the new file ID."""
        file_metadata = {
            "name": name,
            "parents": [folder_id],
        }
        media = MediaIoBaseUpload(
            io.BytesIO(content.encode("utf-8")),
            mimetype="text/markdown",
            resumable=False,
        )
        try:
            with self._lock:
                created = (
                    self._service.files()
                    .create(body=file_metadata, media_body=media, fields="id")
                    .execute()
                )
        except HttpError as e:
            log.error("drive_write_file_failed", name=name, folder_id=folder_id, status=e.status_code, error=str(e))
            raise
        file_id = created["id"]
        path = display_path or name
        log.info("file_created", path=path, file_id=file_id, folder_id=folder_id)
        self._updates.append(path)
        return file_id

    def update_file(self, file_id: str, content: str, display_path: str) -> None:
        """Overwrite the content of an existing file.

        ``display_path`` is a human-readable identifier like ``notes/Directory.yaml``
        used only for logging.
        """
        media = MediaIoBaseUpload(
            io.BytesIO(content.encode("utf-8")),
            mimetype="text/markdown",
            resumable=False,
        )
        try:
            with self._lock:
                self._service.files().update(fileId=file_id, media_body=media).execute()
        except HttpError as e:
            log.error("drive_update_file_failed", file_id=file_id, status=e.status_code, error=str(e))
            raise
        log.info("file_updated", path=display_path)
        self._updates.append(display_path)

    def create_folder(self, parent_id: str, name: str) -> str:
        """Create a subfolder. Returns the new folder ID."""
        file_metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        try:
            with self._lock:
                folder = (
                    self._service.files()
                    .create(body=file_metadata, fields="id")
                    .execute()
                )
        except HttpError as e:
            log.error("drive_create_folder_failed", name=name, parent_id=parent_id, status=e.status_code, error=str(e))
            raise
        folder_id = folder["id"]
        log.info("folder_created", name=name, parent_id=parent_id, folder_id=folder_id)
        return folder_id

    def log_run_summary(self) -> None:
        """Emit a summary log of all files read and updated during this run,
        each list in chronological order."""
        log.info("run_summary", reads=self._reads, updates=self._updates)
