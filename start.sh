#!/usr/bin/env bash
# Academic Weapon launcher for macOS / Linux:  bash start.sh
set -euo pipefail
cd "$(dirname "$0")"

PY="$(command -v python3 || command -v python || true)"
if [[ -z "$PY" ]]; then
  echo "Python 3 isn't installed. Get it from https://www.python.org/downloads/ and run this again."
  exit 1
fi
[[ -x .venv/bin/python ]] || { echo "Setting up the app (first run only)..."; "$PY" -m venv .venv; }
if ! cmp -s requirements.txt .venv/requirements.installed; then
  echo "Installing packages (first run takes a few minutes)..."
  .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
  cp requirements.txt .venv/requirements.installed
fi
if [[ ! -f .env ]] || grep -q "your-key-here" .env; then
  read -r -p "Paste your Anthropic API key (sk-ant-...), or press Enter to skip: " AKEY
  printf "ANTHROPIC_API_KEY=%s\nANTHROPIC_MODEL=claude-sonnet-5-5\n" "$AKEY" > .env
fi
echo "Starting... open http://localhost:8501 if your browser doesn't open by itself. Ctrl+C stops the app."
exec .venv/bin/python -m streamlit run app.py --browser.gatherUsageStats false
