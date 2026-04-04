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

echo "Checking required environment variables..."
python - <<'PY'
import os, pathlib, sys
path = pathlib.Path('.env')
if path.exists():
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
required = ['QOBUZ_USER_AUTH_TOKEN']
missing = [key for key in required if not os.environ.get(key)]
if missing:
    print('Missing required environment variables:', ', '.join(missing))
    print()
    print('Create a .env file in the project root with:')
    print('PYTHONPATH=.')
    print('QOBUZ_APP_ID=100000000')
    print('QOBUZ_USER_AUTH_TOKEN=your_qobuz_token_here')
    sys.exit(1)
PY

python -m streamlit run app.py
