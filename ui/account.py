"""Google sign-in and Google Drive sync, as seen in the UI.

If .streamlit/secrets.toml has no [auth] section the app runs in local-only mode.
"""

import streamlit as st

from core.sync import SyncAction
from core.timeutil import format_local, now_utc
from services import config, db
from services.cloud import is_cloud
from services.drive_sync import DriveAuthError, DriveClient, DriveError, DriveSync

_STATUS = "sync_status"        # (kind, message) shown in the sidebar
_CHECKED = "sync_checked"      # startup sync done for this browser session


def auth_configured() -> bool:
    try:
        return "auth" in st.secrets and "client_id" in st.secrets["auth"]
    except Exception:  # no secrets.toml at all
        return False


def require_login() -> str | None:
    """Show the sign-in screen until the allowed Google account is signed in.

    Returns the signed-in email, or None in local-only mode.
    """
    if not auth_configured():
        if is_cloud():
            # Online, the app must not run without sign-in: the data lives in your Drive
            # and anyone with the link could otherwise use your API key.
            st.title("🎓 Academic Weapon")
            st.error("Google sign-in isn't configured for this deployment. "
                     "Run the deploy script again and enter the Google client ID and secret.")
            st.stop()
        return None

    if not st.user.get("is_logged_in", False):
        st.title("🎓 Academic Weapon")
        st.write("Sign in to load your courses and rank from Google Drive.")
        st.button("Sign in with Google", type="primary", on_click=st.login)
        st.stop()

    email = (st.user.get("email") or "").lower()
    allowed = (config.allowed_email() or "").lower()
    if not allowed:
        st.error("Set ALLOWED_EMAIL in your .env file to your Google address, then restart the app.")
        st.button("Sign out", on_click=st.logout)
        st.stop()
    if email != allowed:
        st.error(f"{email or 'This account'} isn't allowed to use this app.")
        st.button("Sign out and use another account", on_click=st.logout)
        st.stop()
    return email


def _drive_sync(email: str) -> DriveSync | None:
    token = st.user.tokens.get("access")
    if not token:
        st.session_state[_STATUS] = (
            "error", "Google didn't share Drive access. Check expose_tokens in secrets.toml.")
        return None
    return DriveSync(config.db_path(), config.sync_state_path(), DriveClient(token), email)


def _record(action: SyncAction) -> None:
    messages = {
        SyncAction.UPLOAD: "Saved to Google Drive",
        SyncAction.DOWNLOAD: "Loaded latest data from Google Drive",
        SyncAction.NOTHING: "Up to date with Google Drive",
    }
    st.session_state[_STATUS] = ("ok", messages.get(action, "Synced"))


def _record_error(exc: Exception) -> None:
    kind = "auth" if isinstance(exc, DriveAuthError) else "error"
    st.session_state[_STATUS] = (kind, f"{exc} Your changes are safe on this computer.")


def _conflict_screen(sync: DriveSync) -> None:
    with db.open_db(config.db_path()) as conn:
        counts = db.table_counts(conn)
    remote = sync.client.find() or {}
    st.title("⚠️ Two different versions")
    st.write(
        "This computer and Google Drive both have changes that the other doesn't. "
        "Pick the copy to keep. The other one is saved as a backup in `data/backups/`."
    )
    left, right = st.columns(2)
    with left.container(border=True):
        st.subheader("This computer")
        st.write(f"{counts['courses']} courses · {counts['items']} items · {counts['rating_matches']} rated")
        keep_local = st.button("Keep this computer's copy", width="stretch")
    with right.container(border=True):
        st.subheader("Google Drive")
        modified = remote.get("modifiedTime")
        if modified:
            st.write(f"Last saved {format_local(modified[:19] + 'Z')}")
        use_remote = st.button("Use Google Drive's copy", type="primary", width="stretch")

    choice = SyncAction.UPLOAD if keep_local else SyncAction.DOWNLOAD if use_remote else None
    if choice is not None:
        if choice is SyncAction.UPLOAD:
            # Keep a copy of what Drive had before overwriting it
            data = sync.client.download(remote["id"])
            backup_dir = config.db_path().parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = now_utc().strftime("%Y%m%d-%H%M%S")
            (backup_dir / f"drive-before-upload-{stamp}.db").write_bytes(data)
        _record(sync.sync(resolve=choice).action)
        st.session_state[_CHECKED] = True
        st.rerun()
    st.stop()


def _blocked_screen(exc: Exception) -> None:
    st.title("🎓 Academic Weapon")
    if isinstance(exc, DriveAuthError):
        st.warning("Your Google session expired. Sign in again to load your data.")
        st.button("Sign in again", type="primary", on_click=st.logout)
    else:
        st.error(f"Couldn't load your data from Google Drive: {exc}")
        if st.button("Try again", type="primary"):
            st.rerun()
    st.stop()


def unsaved_banner() -> None:
    """Online, unsaved changes disappear when the server sleeps: say so loudly."""
    kind, message = st.session_state.get(_STATUS, ("ok", ""))
    if is_cloud() and kind in ("auth", "error"):
        text, button = st.columns([4, 1], vertical_alignment="center")
        text.error("⚠️ Your latest changes aren't saved to Google Drive yet. " + message)
        if kind == "auth":
            button.button("Sign in again", type="primary", on_click=st.logout, key="banner_login")


def start_sync(email: str | None) -> DriveSync | None:
    """Run once per browser session, before any page reads the database."""
    if email is None:
        return None
    sync = _drive_sync(email)
    if sync is None:
        if is_cloud():
            _blocked_screen(DriveAuthError("Google didn't share Drive access. Sign in again."))
        return None
    if not st.session_state.get(_CHECKED):
        try:
            with st.spinner("Loading your data from Google Drive…"):
                result = sync.sync()
        except DriveError as exc:
            if is_cloud():
                # Online, this server's copy is temporary: never start without your Drive data
                _blocked_screen(exc)
            _record_error(exc)
            st.session_state[_CHECKED] = True
            return sync
        if result.action is SyncAction.CONFLICT:
            _conflict_screen(sync)
        _record(result.action)
        st.session_state[_CHECKED] = True
    return sync


def push_changes(sync: DriveSync | None) -> None:
    """Upload after a page made changes. Runs after every script run; no UI calls here."""
    if sync is None or st.session_state.get(_STATUS, ("",))[0] == "auth":
        return
    try:
        if sync.has_local_changes():
            result = sync.sync()
            if result.action is SyncAction.CONFLICT:
                st.session_state[_CHECKED] = False  # show the chooser on the next run
            else:
                _record(result.action)
    except DriveError as exc:
        _record_error(exc)


def sidebar_status(email: str | None, sync: DriveSync | None) -> None:
    if email is None:
        st.caption("💾 Local only. Set up Google sign-in to save to your account (see README).")
        return
    st.caption(f"Signed in as {email}")
    kind, message = st.session_state.get(_STATUS, ("ok", "Google Drive sync on"))
    if kind == "ok":
        last = sync.last_synced_at() if sync else None
        when = f" · {format_local(last[:19] + 'Z')}" if last else ""
        st.caption(f"☁️ {message}{when}")
    elif kind == "auth":
        st.warning(message)
        st.button("Sign in again", on_click=st.logout, width="stretch")
    else:
        st.warning(message)
    st.button("Sign out", on_click=st.logout, width="stretch", key="sidebar_logout")
