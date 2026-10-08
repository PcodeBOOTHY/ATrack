"""Save the database to the user's Google Drive (hidden app-data folder).

The app always works on the local SQLite file. At sign-in it pulls the Drive copy if
another computer saved newer data; after each change it pushes the local copy up.
If both sides changed, nothing is overwritten until the user picks which copy to keep.
"""

import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from core.sync import SyncAction, decide, md5_hex

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.appdata"
DRIVE_FILE_NAME = "academic_weapon.db"
_API = "https://www.googleapis.com/drive/v3/files"
_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
_SQLITE_HEADER = b"SQLite format 3\x00"
_TIMEOUT = 30


class DriveError(Exception):
    pass


class DriveAuthError(DriveError):
    """The Google access token is missing, expired or lacks the Drive scope."""


class DriveClient:
    """Minimal Drive v3 client for one file in appDataFolder."""

    def __init__(self, access_token: str, session: requests.Session | None = None):
        if not access_token:
            raise DriveAuthError("No Google access token. Sign in again.")
        self._session = session or requests.Session()
        self._headers = {"Authorization": f"Bearer {access_token}"}

    def _check(self, resp) -> None:
        if resp.status_code in (401, 403):
            raise DriveAuthError("Google sign-in expired or Drive access wasn't granted. Sign in again.")
        if resp.status_code >= 400:
            raise DriveError(f"Google Drive error {resp.status_code}: {resp.text[:200]}")

    def find(self) -> dict | None:
        """The app's database file in Drive, as {id, md5Checksum, modifiedTime}, or None."""
        try:
            resp = self._session.get(_API, headers=self._headers, timeout=_TIMEOUT, params={
                "spaces": "appDataFolder",
                "q": f"name = '{DRIVE_FILE_NAME}' and trashed = false",
                "fields": "files(id, md5Checksum, modifiedTime)",
                "orderBy": "modifiedTime desc",
            })
        except requests.RequestException as exc:
            raise DriveError("Could not reach Google Drive. Check your internet connection.") from exc
        self._check(resp)
        files = resp.json().get("files", [])
        return files[0] if files else None

    def download(self, file_id: str) -> bytes:
        try:
            resp = self._session.get(f"{_API}/{file_id}", headers=self._headers,
                                     params={"alt": "media"}, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            raise DriveError("Could not download from Google Drive.") from exc
        self._check(resp)
        return resp.content

    def upload(self, data: bytes, file_id: str | None = None) -> dict:
        """Create the file (first time) or replace its contents. Returns {id, md5Checksum}."""
        params = {"fields": "id, md5Checksum, modifiedTime"}
        try:
            if file_id:
                resp = self._session.patch(
                    f"{_UPLOAD}/{file_id}", headers={**self._headers, "Content-Type": "application/octet-stream"},
                    params={**params, "uploadType": "media"}, data=data, timeout=_TIMEOUT,
                )
            else:
                metadata = {"name": DRIVE_FILE_NAME, "parents": ["appDataFolder"]}
                files = {
                    "metadata": (None, json.dumps(metadata), "application/json; charset=UTF-8"),
                    "file": (DRIVE_FILE_NAME, data, "application/octet-stream"),
                }
                resp = self._session.post(_UPLOAD, headers=self._headers, files=files,
                                          params={**params, "uploadType": "multipart"}, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            raise DriveError("Could not upload to Google Drive.") from exc
        self._check(resp)
        return resp.json()


# --- local database snapshots -----------------------------------------------

def local_snapshot(db_path: Path) -> bytes | None:
    """A consistent byte image of the local database, or None if it doesn't exist."""
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        return conn.serialize()
    finally:
        conn.close()


def is_empty(db_path: Path) -> bool:
    if not db_path.exists():
        return True
    conn = sqlite3.connect(db_path)
    try:
        for table in ("courses", "items"):
            try:
                if conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                    return False
            except sqlite3.OperationalError:
                pass  # table not created yet
        return True
    finally:
        conn.close()


def replace_local(db_path: Path, data: bytes, backup_dir: Path) -> Path | None:
    """Overwrite the local database with downloaded bytes, keeping a backup of the old one."""
    if not data.startswith(_SQLITE_HEADER):
        raise DriveError("The file in Google Drive isn't a valid database; it was not used.")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if db_path.exists():
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = backup_dir / f"app-before-download-{stamp}.db"
        shutil.copy2(db_path, backup)
    tmp = db_path.with_suffix(".download")
    tmp.write_bytes(data)
    os.replace(tmp, db_path)
    return backup


# --- sync -------------------------------------------------------------------

@dataclass
class SyncResult:
    action: SyncAction       # what was done, or CONFLICT if waiting for the user
    backup: Path | None = None


class DriveSync:
    def __init__(self, db_path: Path, state_path: Path, client: DriveClient, account: str):
        self.db_path = Path(db_path)
        self.state_path = Path(state_path)
        self.backup_dir = self.db_path.parent / "backups"
        self.client = client
        self.account = account

    # The sync state lives outside the database so writing it doesn't change the hash.
    def _load_state(self) -> dict:
        try:
            state = json.loads(self.state_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return state if state.get("account") == self.account else {}

    def _save_state(self, base_md5: str | None, file_id: str | None) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({
            "account": self.account, "base_md5": base_md5, "file_id": file_id,
            "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }))

    def has_local_changes(self) -> bool:
        """Cheap check (no network): has the local database changed since the last sync?"""
        data = local_snapshot(self.db_path)
        return data is not None and md5_hex(data) != self._load_state().get("base_md5")

    def last_synced_at(self) -> str | None:
        return self._load_state().get("synced_at")

    def sync(self, resolve: SyncAction | None = None) -> SyncResult:
        """Bring both copies in line. On conflict, pass resolve=UPLOAD or DOWNLOAD to pick a side."""
        data = local_snapshot(self.db_path)
        local = md5_hex(data) if data is not None else None
        remote_file = self.client.find()
        remote = remote_file.get("md5Checksum") if remote_file else None
        file_id = remote_file["id"] if remote_file else None
        base = self._load_state().get("base_md5")

        action = decide(local, remote, base, is_empty(self.db_path))
        if action is SyncAction.CONFLICT:
            if resolve not in (SyncAction.UPLOAD, SyncAction.DOWNLOAD):
                return SyncResult(SyncAction.CONFLICT)
            action = resolve

        backup = None
        if action is SyncAction.UPLOAD:
            result = self.client.upload(data, file_id)
            self._save_state(result.get("md5Checksum") or local, result.get("id") or file_id)
        elif action is SyncAction.DOWNLOAD:
            downloaded = self.client.download(file_id)
            backup = replace_local(self.db_path, downloaded, self.backup_dir)
            self._save_state(md5_hex(downloaded), file_id)
        else:
            self._save_state(local, file_id)
        return SyncResult(action, backup)
