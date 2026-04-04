#!/usr/bin/env bash
set -e

echo "Starting Bandcamp to Qobuz Matcher Web UI..."

if ! command -v python >/dev/null 2>&1; then
  echo "Error: Python is required but was not found on PATH. Install Python 3.10+ and try again."
  exit 1
fi

if [ ! -d ".venv/bin" ]; then
  echo "Creating virtual environment..."
  python -m venv .venv
  echo "Activating virtual environment..."
  # shellcheck source=/dev/null
  source .venv/bin/activate
  echo "Installing dependencies..."
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
else
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

echo "Checking Qobuz environment variables (optional for Dry Run)..."
python - <<'PY'
import os, pathlib
path = pathlib.Path('.env')
if path.exists():
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
if not os.environ.get('QOBUZ_USER_AUTH_TOKEN'):
    print('Warning: QOBUZ_USER_AUTH_TOKEN is missing.')
    print()
    print('Dry Run mode will still work, but Qobuz matching requires this in .env:')
    print('PYTHONPATH=.')
    print('QOBUZ_APP_ID=100000000')
    print('QOBUZ_USER_AUTH_TOKEN=your_qobuz_token_here')
PY

python -m streamlit run app.py
