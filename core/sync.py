"""Decide how to sync the local database with the copy in Google Drive.

Both sides are compared by MD5 hash against `base`: the hash of the copy both sides
agreed on at the last successful sync (stored on this computer).
"""

import hashlib
from enum import Enum


class SyncAction(str, Enum):
    NOTHING = "nothing"      # already in sync
    UPLOAD = "upload"        # only this computer changed (or Drive has no copy yet)
    DOWNLOAD = "download"    # only Drive changed (another computer saved newer data)
    CONFLICT = "conflict"    # both changed since the last sync: ask the user


def md5_hex(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def decide(local: str | None, remote: str | None, base: str | None, local_is_empty: bool) -> SyncAction:
    """
    local:  hash of this computer's database (None if it doesn't exist)
    remote: hash of Drive's copy (None if Drive has none)
    base:   hash at the last successful sync on this computer (None if never synced here)
    local_is_empty: True if this computer has no courses or items yet
    """
    if remote is None:
        return SyncAction.UPLOAD if local is not None else SyncAction.NOTHING
    if local is None or local == remote:
        return SyncAction.DOWNLOAD if local is None else SyncAction.NOTHING
    if base is None:
        # First sync on this computer and the copies differ
        return SyncAction.DOWNLOAD if local_is_empty else SyncAction.CONFLICT
    local_changed, remote_changed = local != base, remote != base
    if local_changed and remote_changed:
        return SyncAction.CONFLICT
    if remote_changed:
        return SyncAction.DOWNLOAD
    return SyncAction.UPLOAD
