import tomllib

from services.cloud import is_cloud, secrets_toml, write_secrets

ENV = {
    "APP_URL": "https://academic-weapon-123.us-central1.run.app/",
    "GOOGLE_CLIENT_ID": "abc.apps.googleusercontent.com",
    "GOOGLE_CLIENT_SECRET": 'GOCSPX-"quoted"\\x',
    "COOKIE_SECRET": "f" * 64,
}


def test_is_cloud():
    assert is_cloud({"K_SERVICE": "academic-weapon"})
    assert not is_cloud({})


def test_secrets_toml_is_valid_and_complete():
    auth = tomllib.loads(secrets_toml(ENV))["auth"]
    assert auth["redirect_uri"] == "https://academic-weapon-123.us-central1.run.app/oauth2callback"
    assert auth["client_secret"] == 'GOCSPX-"quoted"\\x'   # escaping survives
    assert auth["expose_tokens"] == ["access"]
    assert "drive.appdata" in auth["client_kwargs"]["scope"]


def test_missing_values_mean_no_secrets(tmp_path):
    partial = dict(ENV, GOOGLE_CLIENT_SECRET="")
    assert secrets_toml(partial) is None
    assert not write_secrets(tmp_path / "secrets.toml", partial)
    assert write_secrets(tmp_path / ".streamlit" / "secrets.toml", ENV)
    assert (tmp_path / ".streamlit" / "secrets.toml").exists()
