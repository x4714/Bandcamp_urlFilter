#!/usr/bin/env bash
set -e

echo "Starting Bandcamp to Qobuz Matcher Web UI..."
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
export STREAMLIT_SERVER_HEADLESS=true

PYTHON_BIN=""
if command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "Error: Python is required but was not found on PATH. Install Python 3.10+ and try again."
  exit 1
fi

if ! "$PYTHON_BIN" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
then
  echo "Error: $PYTHON_BIN is too old. Bandcamp URL Filter requires Python 3.10+."
  echo "Install or select a newer interpreter and try again."
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating virtual environment..."
  rm -rf .venv
  "$PYTHON_BIN" -m venv .venv
fi

VENV_PYTHON=".venv/bin/python"

if ! "$VENV_PYTHON" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
then
  echo "Existing .venv is not using Python 3.10+; recreating it..."
  rm -rf .venv
  "$PYTHON_BIN" -m venv .venv
  VENV_PYTHON=".venv/bin/python"
fi

echo "Checking dependencies (quiet mode)..."
"$VENV_PYTHON" -m pip install --disable-pip-version-check -q --upgrade pip
"$VENV_PYTHON" -m pip install --disable-pip-version-check -q -r requirements.txt

echo "Checking Qobuz environment variables (optional for Dry Run)..."
"$VENV_PYTHON" - <<'PY'
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

if "$VENV_PYTHON" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 14) else 1)
PY
then
  echo
  echo "Note: Python 3.14+ runs the core app, but the optional streamrip CLI is skipped until upstream adds support."
fi

"$VENV_PYTHON" -m streamlit run app.py --server.headless=true
