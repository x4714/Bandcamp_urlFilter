#!/usr/bin/env fish

echo "Starting Bandcamp to Qobuz Matcher Web UI..."

if not type -q python
    echo "Error: Python is required but was not found on PATH. Install Python 3.10+ and try again."
    exit 1
end

if not test -d .venv/bin
    echo "Creating virtual environment..."
    python -m venv .venv; or exit 1
    echo "Activating virtual environment..."
    source .venv/bin/activate.fish
    echo "Installing dependencies..."
    python -m pip install --upgrade pip; or exit 1
    python -m pip install -r requirements.txt; or exit 1
else if test -f .venv/bin/activate.fish
    source .venv/bin/activate.fish
else
    source .venv/bin/activate
end

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
    print('# Optional: QOBUZ_APP_ID (auto-fetched if omitted)')
    print('QOBUZ_USER_AUTH_TOKEN=your_qobuz_token_here')
PY

python -m streamlit run app.py
