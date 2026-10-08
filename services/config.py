"""Environment-driven settings. Call load() once at app start."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "app.db"
UPLOADS_DIR = PROJECT_ROOT / "data" / "uploads"


def load() -> None:
    load_dotenv(PROJECT_ROOT / ".env")


def anthropic_model() -> str:
    return os.getenv("ANTHROPIC_MODEL") or DEFAULT_MODEL


def has_api_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def db_path() -> Path:
    custom = os.getenv("APP_DB_PATH")
    if not custom:
        return DEFAULT_DB_PATH
    path = Path(custom)
    return path if path.is_absolute() else PROJECT_ROOT / path
