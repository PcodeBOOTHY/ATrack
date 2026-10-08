"""Running on Google Cloud Run: write Streamlit's secrets.toml from environment variables.

Cloud Run sets K_SERVICE automatically. The deploy script stores the Google sign-in
settings as environment variables; this turns them into the [auth] section st.login reads.
"""

import os
from pathlib import Path

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.appdata"
REQUIRED = ("APP_URL", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "COOKIE_SECRET")


def is_cloud(env=os.environ) -> bool:
    return bool(env.get("K_SERVICE"))


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def secrets_toml(env=os.environ) -> str | None:
    """The [auth] section built from env vars, or None if any are missing."""
    if not all(env.get(k) for k in REQUIRED):
        return None
    url = env["APP_URL"].rstrip("/")
    return "\n".join([
        "[auth]",
        f"redirect_uri = {_quote(url + '/oauth2callback')}",
        f"cookie_secret = {_quote(env['COOKIE_SECRET'])}",
        f"client_id = {_quote(env['GOOGLE_CLIENT_ID'])}",
        f"client_secret = {_quote(env['GOOGLE_CLIENT_SECRET'])}",
        'server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"',
        'expose_tokens = ["access"]',
        f'client_kwargs = {{ scope = "openid email profile {DRIVE_SCOPE}", prompt = "select_account" }}',
        "",
    ])


def write_secrets(path: Path, env=os.environ) -> bool:
    """Write .streamlit/secrets.toml if the env has sign-in settings. Returns True if written."""
    content = secrets_toml(env)
    if content is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True
