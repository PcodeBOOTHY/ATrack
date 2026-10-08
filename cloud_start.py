"""Container entry point for Google Cloud Run (see Dockerfile)."""

import os
import sys
from pathlib import Path

from services.cloud import write_secrets

ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    write_secrets(ROOT / ".streamlit" / "secrets.toml")
    port = os.environ.get("PORT", "8080")
    os.execvp(sys.executable, [
        sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
        "--server.port", port, "--server.address", "0.0.0.0", "--server.headless", "true",
    ])
