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
BIND_ADDRESS="${BIND_ADDRESS:-127.0.0.1}"
PORT="${PORT:-}"
NO_START=0
PYTHON_BIN="${PYTHON_BIN:-}"
PYENV_ROOT="${PYENV_ROOT:-$HOME/.local/opt/pyenv}"
PYENV_PYTHON_VERSION="${PYENV_PYTHON_VERSION:-3.11.11}"
SKIP_PYENV_BOOTSTRAP="${SKIP_PYENV_BOOTSTRAP:-0}"

usage() {
  cat <<'EOF'
Usage: ./setup-hbd.sh [options]

Options:
  --port <port>           Use a specific Streamlit port.
  --bind <address>        Bind address for Streamlit. Default: 127.0.0.1
  --service-name <name>   Override the user systemd service name.
  --venv <path>           Override the virtualenv path.
  --app-dir <path>        Override the repository/app directory.
  --env-file <path>       Override the .env path.
  --skip-pyenv-bootstrap  Do not auto-install pyenv when only Python <3.10 is available.
  --no-start              Write/update the service without starting it.
  -h, --help              Show this help text.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      PORT="$2"
      shift 2
      ;;
    --bind)
      BIND_ADDRESS="$2"
      shift 2
      ;;
    --service-name)
      SERVICE_NAME="$2"
      shift 2
      ;;
    --venv)
      VENV_DIR="$2"
      shift 2
      ;;
    --app-dir)
      APP_DIR="$2"
      shift 2
      ;;
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --skip-pyenv-bootstrap)
      SKIP_PYENV_BOOTSTRAP=1
      shift
      ;;
    --no-start)
      NO_START=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

APP_DIR="$(cd "$APP_DIR" && pwd)"
SYSTEMD_DIR="${CONFIG_HOME}/systemd/user"
SERVICE_FILE="${SYSTEMD_DIR}/${SERVICE_NAME}.service"
INSTALL_INFO="${STATE_DIR}/install.env"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
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

pyenv_bin() {
  printf '%s\n' "${PYENV_ROOT}/bin/pyenv"
}

pyenv_available() {
  [[ -x "$(pyenv_bin)" ]]
}

install_pyenv() {
  if pyenv_available; then
    return 0
  fi

  require_command git
  mkdir -p "$(dirname "$PYENV_ROOT")"
  echo "No Python 3.10+ interpreter was found on PATH."
  echo "Bootstrapping pyenv into ${PYENV_ROOT}..."
  git clone https://github.com/pyenv/pyenv.git "$PYENV_ROOT"
}

ensure_pyenv_python() {
  local pyenv_cmd
  pyenv_cmd="$(pyenv_bin)"

  if ! pyenv_available; then
    install_pyenv
  fi

  export PYENV_ROOT
  export PATH="${PYENV_ROOT}/bin:${PATH}"

  if ! "$pyenv_cmd" versions --bare | grep -Fxq "$PYENV_PYTHON_VERSION"; then
    echo "Installing Python ${PYENV_PYTHON_VERSION} with pyenv..."
    mkdir -p "$HOME/.tmp"
    export TMPDIR="$HOME/.tmp"
    if ! "$pyenv_cmd" install "$PYENV_PYTHON_VERSION"; then
      echo "pyenv could not build Python ${PYENV_PYTHON_VERSION}." >&2
      echo "Your box may be missing compiler/runtime dependencies required for source builds." >&2
      echo "If HostingByDesign provides a newer interpreter already, rerun with for example:" >&2
      echo "  PYTHON_BIN=python3.11 ./setup-hbd.sh" >&2
      echo "Otherwise use Docker, or ask the host which Python 3.10+ binary is available." >&2
      return 1
    fi
  fi

  PYTHON_BIN="${PYENV_ROOT}/versions/${PYENV_PYTHON_VERSION}/bin/python3"
  echo "Using pyenv-managed Python: ${PYTHON_BIN}"
}

pick_python() {
  local candidates=()
  local candidate=""
  local found_old=()

  if [[ -n "${PYTHON_BIN}" ]]; then
    candidates+=("${PYTHON_BIN}")
  fi

  candidates+=(
    python3.13
    python3.12
    python3.11
    python3.10
    python3
    python
  )

  for candidate in "${candidates[@]}"; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    if python_version_ok "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
    found_old+=("$candidate")
  done

  if [[ "${#found_old[@]}" -gt 0 ]]; then
    echo "Found Python interpreter(s), but none are new enough: ${found_old[*]}" >&2
  else
    echo "Python 3.10+ was not found on PATH." >&2
  fi

  if [[ "$SKIP_PYENV_BOOTSTRAP" == "1" ]]; then
    echo "Bandcamp URL Filter requires Python 3.10+." >&2
    echo "Automatic pyenv bootstrap is disabled." >&2
    echo "Rerun with for example:" >&2
    echo "  PYTHON_BIN=python3.11 ./setup-hbd.sh" >&2
    echo "Or allow pyenv bootstrap by omitting --skip-pyenv-bootstrap." >&2
    return 1
  fi

  ensure_pyenv_python || return 1
  printf '%s\n' "$PYTHON_BIN"
}

pick_port() {
  "$PYTHON_BIN" - "${1:-8501}" "${2:-8999}" <<'PY'
import socket
import sys

start = int(sys.argv[1])
end = int(sys.argv[2])

for port in range(start, end + 1):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            continue
        print(port)
        break
else:
    raise SystemExit("No free port available in the requested range.")
PY
}

require_command systemctl
PYTHON_BIN="$(pick_python)"

mkdir -p "$CONFIG_HOME" "$STATE_DIR" "$SYSTEMD_DIR" "$APP_DIR/exports"

if [[ -z "$PORT" && -f "$PORT_FILE" ]]; then
  PORT="$(tr -d '[:space:]' < "$PORT_FILE")"
fi

if [[ -z "$PORT" ]]; then
  PORT="$(pick_port 8501 8999)"
fi

if [[ ! "$PORT" =~ ^[0-9]+$ ]]; then
  echo "Port must be numeric." >&2
  exit 1
fi

echo "Preparing ${APP_NAME} for a HostingByDesign-style user service..."
echo "App directory: ${APP_DIR}"
echo "Python: ${PYTHON_BIN}"
echo "Virtualenv: ${VENV_DIR}"
echo "Service: ${SERVICE_NAME}"
echo "Bind: ${BIND_ADDRESS}:${PORT}"
if [[ "$PYTHON_BIN" == "${PYENV_ROOT}/versions/"* ]]; then
  echo "Python source: pyenv (${PYENV_PYTHON_VERSION})"
fi

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating virtual environment..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

if ! python_version_ok "${VENV_DIR}/bin/python"; then
  echo "Existing virtualenv is not using Python 3.10+; recreating ${VENV_DIR}..."
  rm -rf "$VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

VENV_PYTHON="${VENV_DIR}/bin/python"
VENV_PYTHON_VERSION="$(python_version_string "$VENV_PYTHON")"
echo "Virtualenv Python: ${VENV_PYTHON_VERSION}"

echo "Installing Python dependencies..."
"${VENV_PYTHON}" -m pip install --upgrade pip
"${VENV_PYTHON}" -m pip install -r "${APP_DIR}/requirements.txt"

if [[ ! -f "$ENV_FILE" && -f "$EXAMPLE_ENV_FILE" ]]; then
  cp "$EXAMPLE_ENV_FILE" "$ENV_FILE"
  echo "Created ${ENV_FILE} from .env.example. Fill in your Qobuz token before live matching."
fi

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Bandcamp URL Filter Streamlit UI
After=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
Environment=HOME=${HOME}
Environment=PYTHONPATH=${APP_DIR}
Environment=XDG_CONFIG_HOME=${CONFIG_HOME}
Environment=STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
ExecStart=${VENV_PYTHON} -m streamlit run ${APP_DIR}/app.py --server.headless=true --server.address=${BIND_ADDRESS} --server.port=${PORT}
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
EOF

printf '%s\n' "$PORT" > "$PORT_FILE"

echo "Reloading user systemd units..."
systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME" >/dev/null

if [[ "$NO_START" -eq 0 ]]; then
  echo "Starting ${SERVICE_NAME}..."
  systemctl --user restart "$SERVICE_NAME"
fi

echo
echo "Setup complete."
echo "Service file: ${SERVICE_FILE}"
echo "Stored install info: ${INSTALL_INFO}"
echo "Port: ${PORT}"
echo
echo "Useful commands:"
echo "  systemctl --user status ${SERVICE_NAME}"
echo "  journalctl --user -u ${SERVICE_NAME} -f"
echo "  systemctl --user restart ${SERVICE_NAME}"
echo
if [[ "$BIND_ADDRESS" == "127.0.0.1" ]]; then
  echo "The app is bound to localhost for safety."
  echo "Open it with an SSH tunnel, for example:"
  echo "  ssh -N -L ${PORT}:127.0.0.1:${PORT} ${USER}@your-box"
else
  echo "Open: http://${BIND_ADDRESS}:${PORT}"
fi
