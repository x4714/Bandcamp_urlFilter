#!/usr/bin/env bash
set -euo pipefail

APP_NAME="bandcamp-urlfilter"
SERVICE_NAME="${SERVICE_NAME:-$APP_NAME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$SCRIPT_DIR}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
VENV_DIR="${VENV_DIR:-$CONFIG_HOME/venv/$SERVICE_NAME}"
STATE_DIR="${STATE_DIR:-$CONFIG_HOME/$SERVICE_NAME}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"
EXAMPLE_ENV_FILE="${APP_DIR}/.env.example"
PORT_FILE="${STATE_DIR}/port"
BIND_ADDRESS="${BIND_ADDRESS:-0.0.0.0}"   # HBD panel proxies via itsby.design
PORT="${PORT:-}"
NO_START=0
AUTH_SETUP_MODE="${AUTH_SETUP_MODE:-auto}"
PYTHON_BIN="${PYTHON_BIN:-}"
PYENV_ROOT="${PYENV_ROOT:-$HOME/.local/opt/pyenv}"
PYENV_PYTHON_VERSION="${PYENV_PYTHON_VERSION:-3.11.11}"
SKIP_PYENV_BOOTSTRAP="${SKIP_PYENV_BOOTSTRAP:-0}"

mkdir -p "$HOME/.logs/"
export log="$HOME/.logs/${APP_NAME}.log"
touch "$log"

usage() {
  cat <<'EOF'
Usage: ./setup-hbd.sh [options]

Options:
  --port <port>           Use a specific port.
  --bind <address>        Bind address. Default: 0.0.0.0
  --service-name <name>   Override the user systemd service name.
  --venv <path>           Override the virtualenv path.
  --app-dir <path>        Override the repository/app directory.
  --env-file <path>       Override the .env path.
  --enable-auth           Force app auth setup during install.
  --disable-auth          Skip app auth setup for non-public binds only.
  --skip-pyenv-bootstrap  Do not auto-install pyenv when only Python <3.10 is available.
  --no-start              Write/update the service without starting it.
  -h, --help              Show this help text.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)                 PORT="$2";           shift 2 ;;
    --bind)                 BIND_ADDRESS="$2";   shift 2 ;;
    --service-name)         SERVICE_NAME="$2";   shift 2 ;;
    --venv)                 VENV_DIR="$2";       shift 2 ;;
    --app-dir)              APP_DIR="$2";        shift 2 ;;
    --env-file)             ENV_FILE="$2";       shift 2 ;;
    --enable-auth)          AUTH_SETUP_MODE="enable"; shift ;;
    --disable-auth)         AUTH_SETUP_MODE="disable"; shift ;;
    --skip-pyenv-bootstrap) SKIP_PYENV_BOOTSTRAP=1; shift ;;
    --no-start)             NO_START=1;          shift ;;
    -h|--help)              usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
done

APP_DIR="$(cd "$APP_DIR" && pwd)"
SYSTEMD_DIR="${CONFIG_HOME}/systemd/user"
SERVICE_FILE="${SYSTEMD_DIR}/${SERVICE_NAME}.service"
INSTALL_INFO="${STATE_DIR}/install.env"
LOCK_FILE="$HOME/.install/.${APP_NAME}.lock"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

function port() {
    LOW_BOUND=$1
    UPPER_BOUND=$2
    comm -23 \
      <(seq "${LOW_BOUND}" "${UPPER_BOUND}" | sort) \
      <(ss -Htan | awk '{print $4}' | cut -d':' -f2 | sort -u) \
      | shuf | head -n 1
}

python_version_ok() {
  local candidate="$1"
  "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

python_version_string() {
  local candidate="$1"
  "$candidate" - <<'PY'
import sys
print(".".join(str(part) for part in sys.version_info[:3]))
PY
}

is_public_bind() {
  case "$1" in
    127.0.0.1|localhost|::1) return 1 ;;
    *) return 0 ;;
  esac
}

should_setup_auth() {
  case "$AUTH_SETUP_MODE" in
    enable) return 0 ;;
    disable)
      if is_public_bind "$BIND_ADDRESS"; then
        echo "Refusing to disable app auth for public bind ${BIND_ADDRESS}." >&2
        echo "Use --bind 127.0.0.1 if you want to run without built-in app auth." >&2
        exit 1
      fi
      return 1
      ;;
    auto)
      if ! is_public_bind "$BIND_ADDRESS"; then
        return 1
      fi
      if [[ ! -t 0 ]]; then
        echo "Public bind detected (${BIND_ADDRESS}), but stdin is non-interactive." >&2
        echo "Built-in app auth is required for public-facing HBD installs." >&2
        echo "Re-run in an interactive shell so the installer can set app credentials." >&2
        exit 1
      fi
      echo ""
      echo "This install is binding to ${BIND_ADDRESS}, which is typically used behind a public HBD domain."
      echo "HBD basic auth is not available for third-party apps, so built-in app auth will be configured now."
      return 0
      ;;
    *)
      echo "Unknown AUTH_SETUP_MODE: ${AUTH_SETUP_MODE}" >&2
      exit 1
      ;;
  esac
}

upsert_env_value() {
  local key="$1"
  local value="$2"
  local file="$3"
  local tmp_file

  tmp_file="$(mktemp)"
  awk -v key="$key" -v value="$value" '
    BEGIN { updated = 0 }
    index($0, key "=") == 1 {
      print key "=" value
      updated = 1
      next
    }
    { print }
    END {
      if (!updated) {
        print key "=" value
      }
    }
  ' "$file" > "$tmp_file"
  mv "$tmp_file" "$file"
}

build_password_hash() {
  local password="$1"

  "$VENV_PYTHON" - "$password" <<'PY'
import base64
import hashlib
import os
import sys

password = sys.argv[1].encode("utf-8")
salt = os.urandom(16)
iterations = 390000
digest = hashlib.pbkdf2_hmac("sha256", password, salt, iterations)
print(
    "pbkdf2_sha256"
    f"${iterations}"
    f"${base64.b64encode(salt).decode('ascii')}"
    f"${base64.b64encode(digest).decode('ascii')}"
)
PY
}

setup_required_auth() {
  local user password password_confirm password_hash

  if ! should_setup_auth; then
    return 0
  fi

  if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$EXAMPLE_ENV_FILE" ]]; then
      cp "$EXAMPLE_ENV_FILE" "$ENV_FILE"
    else
      : > "$ENV_FILE"
    fi
  fi

  if command -v whoami >/dev/null 2>&1; then
    user="$(whoami)"
  else
    user="$(id -un)"
  fi

  echo ""
  echo "Configuring required app auth for user ${user}..."
  echo "Use a strong password here. This app will be reachable on the public web."

  while true; do
    read -r -s -p "Please set a password for your app user ${user}> " password
    echo ""
    read -r -s -p "Confirm password for ${user}> " password_confirm
    echo ""

    if [[ -z "$password" ]]; then
      echo "Password cannot be empty." >&2
      continue
    fi
    if [[ "${#password}" -lt 16 ]]; then
      echo "Password must be at least 16 characters for a public-facing app." >&2
      continue
    fi
    if [[ "$password" == "$user" ]]; then
      echo "Password must not match the username." >&2
      continue
    fi
    if [[ "$password" =~ [[:space:]] ]]; then
      echo "Password must not contain whitespace." >&2
      continue
    fi
    if [[ "$password" != "$password_confirm" ]]; then
      echo "Passwords did not match. Try again." >&2
      continue
    fi
    break
  done

  password_hash="$(build_password_hash "$password")"
  chmod 600 "$ENV_FILE" 2>/dev/null || true
  upsert_env_value "APP_AUTH_ENABLED" "1" "$ENV_FILE"
  upsert_env_value "APP_AUTH_USERNAME" "$user" "$ENV_FILE"
  upsert_env_value "APP_AUTH_PASSWORD_HASH" "$password_hash" "$ENV_FILE"

  unset password
  unset password_confirm
  unset password_hash
  echo "App auth configured for ${user} in ${ENV_FILE}."
}

pyenv_bin()       { printf '%s\n' "${PYENV_ROOT}/bin/pyenv"; }
pyenv_available() { [[ -x "$(pyenv_bin)" ]]; }

install_pyenv() {
  if pyenv_available; then return 0; fi
  require_command git
  mkdir -p "$(dirname "$PYENV_ROOT")"
  echo "No Python 3.10+ interpreter found on PATH." >&2
  echo "Bootstrapping pyenv into ${PYENV_ROOT}..." >&2
  git clone https://github.com/pyenv/pyenv.git "$PYENV_ROOT" >> "$log" 2>&1
}

ensure_pyenv_python() {
  local pyenv_cmd
  pyenv_cmd="$(pyenv_bin)"
  if ! pyenv_available; then install_pyenv; fi

  export PYENV_ROOT
  export PATH="${PYENV_ROOT}/bin:${PATH}"

  if ! "$pyenv_cmd" versions --bare | grep -Fxq "$PYENV_PYTHON_VERSION"; then
    echo "Installing Python ${PYENV_PYTHON_VERSION} via pyenv..." >&2
    mkdir -p "$HOME/.tmp"
    export TMPDIR="$HOME/.tmp"
    if ! "$pyenv_cmd" install "$PYENV_PYTHON_VERSION" >> "$log" 2>&1; then
      echo "pyenv could not build Python ${PYENV_PYTHON_VERSION}." >&2
      echo "Rerun with e.g.: PYTHON_BIN=python3.11 ./setup-hbd.sh" >&2
      return 1
    fi
  fi

  PYTHON_BIN="${PYENV_ROOT}/versions/${PYENV_PYTHON_VERSION}/bin/python3"
  echo "Using pyenv-managed Python: ${PYTHON_BIN}" >&2
}

pick_python() {
  local candidates=() candidate="" found_old=()
  if [[ -n "${PYTHON_BIN}" ]]; then candidates+=("${PYTHON_BIN}"); fi
  candidates+=(python3.13 python3.12 python3.11 python3.10 python3 python)

  for candidate in "${candidates[@]}"; do
    if ! command -v "$candidate" >/dev/null 2>&1; then continue; fi
    if python_version_ok "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
    found_old+=("$candidate")
  done

  if [[ "${#found_old[@]}" -gt 0 ]]; then
    echo "Found Python interpreter(s), but none are new enough: ${found_old[*]}" >&2
  else
    echo "Python 3.10+ not found on PATH." >&2
  fi

  if [[ "$SKIP_PYENV_BOOTSTRAP" == "1" ]]; then
    echo "Rerun with e.g.: PYTHON_BIN=python3.11 ./setup-hbd.sh" >&2
    return 1
  fi

  ensure_pyenv_python || return 1
  printf '%s\n' "$PYTHON_BIN"
}

function _install() {
    if [[ -f "$LOCK_FILE" ]]; then
        echo "${APP_NAME} is already installed. Use 'upgrade' or 'uninstall' first."
        exit 1
    fi

    require_command systemctl
    PYTHON_BIN="$(pick_python)"

    if [[ -z "$PORT" && -f "$PORT_FILE" ]]; then
        PORT="$(tr -d '[:space:]' < "$PORT_FILE")"
    fi
    if [[ -z "$PORT" ]]; then
        PORT="$(port 10300 10500)"
    fi
    if [[ ! "$PORT" =~ ^[0-9]+$ ]]; then
        echo "Port must be numeric." >&2
        exit 1
    fi

    mkdir -p "$CONFIG_HOME" "$STATE_DIR" "$SYSTEMD_DIR" "$APP_DIR/exports" "$HOME/.install"

    echo "Preparing ${APP_NAME}..."
    echo "App directory : ${APP_DIR}"
    echo "Python        : ${PYTHON_BIN}"
    echo "Virtualenv    : ${VENV_DIR}"
    echo "Bind          : ${BIND_ADDRESS}:${PORT}"

    if [[ ! -d "$VENV_DIR" ]]; then
        echo "Creating virtual environment..."
        "$PYTHON_BIN" -m venv "$VENV_DIR"
    fi

    if ! python_version_ok "${VENV_DIR}/bin/python"; then
        echo "Existing virtualenv is not Python 3.10+; recreating..."
        rm -rf "$VENV_DIR"
        "$PYTHON_BIN" -m venv "$VENV_DIR"
    fi

    VENV_PYTHON="${VENV_DIR}/bin/python"
    echo "Virtualenv Python: $(python_version_string "$VENV_PYTHON")"

    if [[ ! -f "$ENV_FILE" && -f "$EXAMPLE_ENV_FILE" ]]; then
        cp "$EXAMPLE_ENV_FILE" "$ENV_FILE"
        echo "Created ${ENV_FILE} from .env.example - fill in your Qobuz token before live matching."
    fi

    echo "Installing Python dependencies..."
    "${VENV_PYTHON}" -m pip install --upgrade pip >> "$log" 2>&1
    "${VENV_PYTHON}" -m pip install -r "${APP_DIR}/requirements.txt" 2>&1 | tee -a "$log"
    setup_required_auth

    local svc_type=simple
    if [[ $(systemctl --version | awk 'NR==1 {print $2}') -ge 240 ]]; then
        svc_type=exec
    fi

    echo "Installing systemd service..."
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Bandcamp URL Filter Streamlit UI
After=syslog.target network.target

[Service]
Type=${svc_type}
WorkingDirectory=${APP_DIR}
Environment=HOME=${HOME}
Environment=PYTHONPATH=${APP_DIR}
Environment=XDG_CONFIG_HOME=${CONFIG_HOME}
Environment=STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
ExecStart=${VENV_DIR}/bin/python -m streamlit run ${APP_DIR}/app.py \
    --server.headless=true \
    --server.address=${BIND_ADDRESS} \
    --server.port=${PORT}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

    cat > "$INSTALL_INFO" <<EOF
APP_DIR=${APP_DIR}
ENV_FILE=${ENV_FILE}
PORT=${PORT}
BIND_ADDRESS=${BIND_ADDRESS}
PYTHON_BIN=${PYTHON_BIN}
SERVICE_NAME=${SERVICE_NAME}
SERVICE_FILE=${SERVICE_FILE}
VENV_DIR=${VENV_DIR}
AUTH_SETUP_MODE=${AUTH_SETUP_MODE}
EOF

    printf '%s\n' "$PORT" > "$PORT_FILE"

    systemctl --user daemon-reload
    systemctl --user enable --now "$SERVICE_NAME" 2>&1 | tee -a "$log"

    touch "$LOCK_FILE"

    echo ""
    echo "${APP_NAME} is now installed and running." | tee -a "$log"
    echo "Open it at: http://$(hostname -f):${PORT}/" | tee -a "$log"
    echo "(The HBD panel will proxy this through your itsby.design URL automatically.)"
    if is_public_bind "$BIND_ADDRESS"; then
        echo "Built-in app auth is enabled because this install is reachable on a public domain."
    fi
    echo ""
    echo "Useful commands:"
    echo "  systemctl --user status  ${SERVICE_NAME}"
    echo "  journalctl --user -u ${SERVICE_NAME} -f"
    echo "  systemctl --user restart ${SERVICE_NAME}"
}

function _upgrade() {
    if [[ ! -f "$LOCK_FILE" ]]; then
        echo "${APP_NAME} is not installed!"
        exit 1
    fi

    # shellcheck disable=SC1090
    source "$INSTALL_INFO"

    echo "Upgrading Python dependencies..."
    "${VENV_DIR}/bin/python" -m pip install --upgrade pip >> "$log" 2>&1
    "${VENV_DIR}/bin/python" -m pip install --upgrade -r "${APP_DIR}/requirements.txt" 2>&1 | tee -a "$log"

    systemctl --user try-restart "$SERVICE_NAME"
    echo "Upgrade complete."
}

function _remove() {
    if [[ ! -f "$LOCK_FILE" ]]; then
        echo "${APP_NAME} is not installed!"
        exit 1
    fi

    systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$SERVICE_FILE"
    systemctl --user daemon-reload
    rm -rf "$VENV_DIR" "$STATE_DIR"
    rm -f "$LOCK_FILE"
    echo "${APP_NAME} has been removed."
    echo "Your app files in ${APP_DIR} and .env were left intact."
}

echo 'This is unsupported software. You will not get help with this, please answer `yes` if you understand and wish to proceed'
if [[ -z "${eula:-}" ]]; then
    read -r eula
fi
if ! [[ $eula =~ yes ]]; then
    echo "You did not accept the above. Exiting..."
    exit 1
else
    echo "Proceeding..."
fi

echo ""
echo "Welcome to the ${APP_NAME} installer"
echo "Logs are stored at ${log}"
echo ""
echo "What would you like to do?"
echo "  install   = Install ${APP_NAME}"
echo "  upgrade   = Upgrade dependencies to latest"
echo "  uninstall = Completely remove ${APP_NAME}"
echo "  exit      = Exit"

while true; do
    read -r -p "Enter it here: " choice
    case $choice in
        install)   _install;  break ;;
        upgrade)   _upgrade;  break ;;
        uninstall) _remove;   break ;;
        exit)                 break ;;
        *) echo "Unknown option." ;;
    esac
done
