#!/usr/bin/env bash
set -euo pipefail

echo "Starting Bandcamp to Qobuz Matcher Web UI..."
export STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
export STREAMLIT_SERVER_HEADLESS=true

PYTHON_BIN="${PYTHON_BIN:-}"
PYENV_ROOT="${PYENV_ROOT:-$HOME/.local/opt/pyenv}"
PYENV_PYTHON_VERSION_DEFAULT="3.11.11"
PYENV_PYTHON_VERSION_IS_EXPLICIT="${PYENV_PYTHON_VERSION+x}"
PYENV_PYTHON_VERSION="${PYENV_PYTHON_VERSION:-$PYENV_PYTHON_VERSION_DEFAULT}"
SKIP_PYENV_BOOTSTRAP="${SKIP_PYENV_BOOTSTRAP:-0}"

python_version_ok() {
  local candidate="$1"
  "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if (3, 9) <= sys.version_info < (3, 14) else 1)
PY
}

python_version_string() {
  local candidate="$1"
  "$candidate" - <<'PY'
import sys
print(".".join(str(part) for part in sys.version_info[:3]))
PY
}

python_modules_ok() {
  local candidate="$1"
  "$candidate" -c "import _sqlite3, _ssl, _hashlib, zlib" >/dev/null 2>&1
}

pyenv_bin() {
  if [[ -x "${PYENV_ROOT}/bin/pyenv" ]]; then
    printf '%s\n' "${PYENV_ROOT}/bin/pyenv"
    return 0
  fi

  if command -v pyenv >/dev/null 2>&1; then
    command -v pyenv
    return 0
  fi

  return 1
}

pyenv_available() {
  pyenv_bin >/dev/null 2>&1
}

install_pyenv() {
  if pyenv_available; then return 0; fi
  if ! command -v git >/dev/null 2>&1; then
    echo "Error: git is required to bootstrap pyenv but was not found on PATH." >&2
    return 1
  fi

  if [[ -d "$PYENV_ROOT" ]] && [[ -n "$(ls -A "$PYENV_ROOT" 2>/dev/null)" ]]; then
    echo "Error: ${PYENV_ROOT} exists and is not empty, but no pyenv executable was found." >&2
    echo "Set PYENV_ROOT to an empty directory, install pyenv, or set SKIP_PYENV_BOOTSTRAP=1." >&2
    return 1
  fi

  mkdir -p "$(dirname "$PYENV_ROOT")"
  echo "No compatible Python (3.9-3.13) found on PATH." >&2
  echo "Bootstrapping pyenv into ${PYENV_ROOT}..." >&2
  echo "(This can take a minute - cloning pyenv from GitHub.)" >&2
  git clone https://github.com/pyenv/pyenv.git "$PYENV_ROOT"
}

ensure_pyenv_python() {
  if ! pyenv_available; then install_pyenv || return 1; fi

  export PYENV_ROOT

  local pyenv_cmd
  pyenv_cmd="$(pyenv_bin)" || {
    echo "Error: pyenv is not available after bootstrap attempt." >&2
    return 1
  }

  if [[ "$pyenv_cmd" == "${PYENV_ROOT}/bin/pyenv" ]]; then
    export PATH="${PYENV_ROOT}/bin:${PATH}"
  fi

  local available_versions chosen_installed_version
  available_versions="$("$pyenv_cmd" versions --bare 2>/dev/null || true)"

  if ! grep -Fxq "$PYENV_PYTHON_VERSION" <<<"$available_versions"; then
    chosen_installed_version=""
    if [[ -z "$PYENV_PYTHON_VERSION_IS_EXPLICIT" ]]; then
      chosen_installed_version="$(
        printf '%s\n' "$available_versions" \
          | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' \
          | awk -F. '$1 == 3 && $2 >= 9 && $2 <= 13 { print $0 }' \
          | sort -V \
          | tail -n 1
      )"
    fi

    if [[ -n "$chosen_installed_version" ]]; then
      PYENV_PYTHON_VERSION="$chosen_installed_version"
      echo "Using installed pyenv Python ${PYENV_PYTHON_VERSION}." >&2
    else
      echo "Installing Python ${PYENV_PYTHON_VERSION} with pyenv..." >&2
      echo "(This can take up to 10 minutes.)" >&2
      if ! "$pyenv_cmd" install "$PYENV_PYTHON_VERSION"; then
        echo "Error: pyenv failed to install Python ${PYENV_PYTHON_VERSION}." >&2
        return 1
      fi
    fi
  fi

  PYTHON_BIN="${PYENV_ROOT}/versions/${PYENV_PYTHON_VERSION}/bin/python3"

  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Error: expected Python binary not found at ${PYTHON_BIN}." >&2
    return 1
  fi

  if ! python_version_ok "$PYTHON_BIN"; then
    echo "Error: pyenv Python ${PYENV_PYTHON_VERSION} is outside the supported range (3.9-3.13)." >&2
    return 1
  fi
  if ! python_modules_ok "$PYTHON_BIN"; then
    echo "Error: pyenv Python ${PYENV_PYTHON_VERSION} is missing required modules (sqlite3/ssl/zlib)." >&2
    return 1
  fi
}

pick_python() {
  local candidates=() candidate=""
  local found_incompatible=()

  if [[ -n "$PYTHON_BIN" ]]; then candidates+=("$PYTHON_BIN"); fi
  candidates+=(python3.13 python3.12 python3.11 python3.10 python3.9 python3 python)

  for candidate in "${candidates[@]}"; do
    if ! command -v "$candidate" >/dev/null 2>&1; then continue; fi
    if python_version_ok "$candidate"; then
      if python_modules_ok "$candidate"; then
        PYTHON_BIN="$candidate"
        return 0
      fi
      echo "Python at ${candidate} is missing compiled modules (sqlite3/ssl), skipping." >&2
      continue
    fi
    found_incompatible+=("${candidate}:$(python_version_string "$candidate")")
  done

  if [[ "${#found_incompatible[@]}" -gt 0 ]]; then
    echo "Found Python interpreter(s), but none are compatible with this repo: ${found_incompatible[*]}" >&2
  else
    echo "No compatible Python (3.9-3.13) found on PATH." >&2
  fi

  if [[ "$SKIP_PYENV_BOOTSTRAP" == "1" ]]; then
    echo "Set PYTHON_BIN to a Python 3.9-3.13 executable and rerun." >&2
    return 1
  fi

  ensure_pyenv_python || return 1
  return 0
}

pick_python
echo "Using Python runtime: $("$PYTHON_BIN" -V 2>&1)"

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating virtual environment..."
  rm -rf .venv
  "$PYTHON_BIN" -m venv .venv
fi

VENV_PYTHON=".venv/bin/python"

if ! python_version_ok "$VENV_PYTHON"; then
  echo "Existing .venv is not using Python 3.9-3.13; recreating it..."
  rm -rf .venv
  "$PYTHON_BIN" -m venv .venv
  VENV_PYTHON=".venv/bin/python"
fi

if ! python_modules_ok "$VENV_PYTHON"; then
  echo "Existing .venv Python is missing sqlite3/ssl/zlib modules; recreating it..."
  rm -rf .venv
  "$PYTHON_BIN" -m venv .venv
  VENV_PYTHON=".venv/bin/python"
fi

echo "Checking dependencies (quiet mode)..."
"$VENV_PYTHON" -m pip install --disable-pip-version-check -q --upgrade pip
"$VENV_PYTHON" -m pip install --disable-pip-version-check -q -r requirements.txt

echo "Checking Qobuz environment variables (optional for Dry Run)..."
"$VENV_PYTHON" - <<'PY'
import os
from pathlib import Path
from dotenv import dotenv_values

path = Path(".env")
if path.exists():
    for key, value in dotenv_values(path).items():
        if key:
            os.environ.setdefault(key, "" if value is None else str(value))
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
raise SystemExit(0 if sys.version_info < (3, 10) else 1)
PY
then
  echo
  echo "Note: Python 3.9 runs the core app, but bundled streamrip install is only enabled on Python 3.10-3.13."
fi

"$VENV_PYTHON" -m streamlit run app.py --server.headless=true
