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
BIND_ADDRESS="${BIND_ADDRESS:-0.0.0.0}"
PORT="${PORT:-}"
NO_START=0
AUTH_SETUP_MODE="${AUTH_SETUP_MODE:-auto}"
PYTHON_BIN="${PYTHON_BIN:-}"
PYENV_ROOT="${PYENV_ROOT:-$HOME/.local/opt/pyenv}"
PYENV_PYTHON_VERSION="${PYENV_PYTHON_VERSION:-3.11.11}"
SKIP_PYENV_BOOTSTRAP="${SKIP_PYENV_BOOTSTRAP:-0}"
LOCAL_DEPS_DIR="${LOCAL_DEPS_DIR:-$HOME/.local}"
SQLITE_VERSION="${SQLITE_VERSION:-3450300}"   # 3.45.3
SQLITE_YEAR="${SQLITE_YEAR:-2024}"
OPENSSL_VERSION="${OPENSSL_VERSION:-3.3.2}"

mkdir -p "$HOME/.logs/"
export log="$HOME/.logs/${APP_NAME}.log"
touch "$log"

usage() {
  cat <<'EOF'
Usage: ./setup-hbd.sh [options]

Options:
  --port <port>           Use a specific port.
  --bind <address>        Bind address. Default: 0.0.0.0
  --service-name <n>      Override the user systemd service name.
  --venv <path>           Override the virtualenv path.
  --app-dir <path>        Override the repository/app directory.
  --env-file <path>       Override the .env path.
  --enable-auth           Force app auth setup during install.
  --disable-auth          Skip app auth setup (localhost bind only).
  --skip-pyenv-bootstrap  Do not auto-install pyenv when no Python 3.9-3.13 is available.
  --no-start              Write/update the service without starting it.
  -h, --help              Show this help text.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)                 PORT="$2";                 shift 2 ;;
    --bind)                 BIND_ADDRESS="$2";         shift 2 ;;
    --service-name)         SERVICE_NAME="$2";         shift 2 ;;
    --venv)                 VENV_DIR="$2";             shift 2 ;;
    --app-dir)              APP_DIR="$2";              shift 2 ;;
    --env-file)             ENV_FILE="$2";             shift 2 ;;
    --enable-auth)          AUTH_SETUP_MODE="enable";  shift ;;
    --disable-auth)         AUTH_SETUP_MODE="disable"; shift ;;
    --skip-pyenv-bootstrap) SKIP_PYENV_BOOTSTRAP=1;   shift ;;
    --no-start)             NO_START=1;                shift ;;
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

# ── Python version checks ─────────────────────────────────────────────────────

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
  "$candidate" -c "import _sqlite3, _ssl, _hashlib, zlib" 2>/dev/null
}

# ── pyenv bootstrap ───────────────────────────────────────────────────────────

pyenv_bin()       { printf '%s\n' "${PYENV_ROOT}/bin/pyenv"; }
pyenv_available() { [[ -x "$(pyenv_bin)" ]]; }

install_pyenv() {
  if pyenv_available; then return 0; fi
  require_command git
  mkdir -p "$(dirname "$PYENV_ROOT")"
  echo "No compatible Python (3.9-3.13) interpreter found on PATH." >&2
  echo "Bootstrapping pyenv into ${PYENV_ROOT}..." >&2
  echo "(This can take a minute — cloning pyenv from GitHub.)" >&2
  git clone https://github.com/pyenv/pyenv.git "$PYENV_ROOT" >> "$log" 2>&1
}

# ── Local dep bootstrap (no-sudo SQLite / OpenSSL from source) ───────────────

# Returns 0 if a header is findable in standard or LOCAL_DEPS_DIR locations.
header_exists() {
  local header="$1"
  for dir in /usr/include /usr/include/x86_64-linux-gnu "${LOCAL_DEPS_DIR}/include"; do
    [[ -f "${dir}/${header}" ]] && return 0
  done
  return 1
}

# Returns 0 if the given SQLite shared lib exports sqlite3_deserialize,
# which was added in 3.23.0 (2018). We check the binary directly rather
# than trusting system headers, which can come from a newer package than
# the actual .so (exactly the situation that causes the cpython .so to
# compile fine but blow up at runtime with "undefined symbol").
sqlite_lib_ok() {
  local lib="$1"
  [[ -f "$lib" ]] || return 1
  nm -D "$lib" 2>/dev/null | grep -q "sqlite3_deserialize"
}

_bootstrap_sqlite() {
  local tarball="$HOME/.tmp/sqlite-autoconf-${SQLITE_VERSION}.tar.gz"
  local src_dir="$HOME/.tmp/sqlite-autoconf-${SQLITE_VERSION}"
  echo "Building SQLite ${SQLITE_VERSION} from source (no sudo)..." >&2
  echo "(This can take up to 2 minutes.)" >&2
  mkdir -p "$HOME/.tmp" "${LOCAL_DEPS_DIR}"
  if [[ ! -f "$tarball" ]]; then
    curl -fsSL \
      "https://www.sqlite.org/${SQLITE_YEAR}/sqlite-autoconf-${SQLITE_VERSION}.tar.gz" \
      -o "$tarball" >> "$log" 2>&1 \
      || { echo "ERROR: Failed to download SQLite tarball." >&2; return 1; }
  fi
  tar xf "$tarball" -C "$HOME/.tmp" >> "$log" 2>&1
  (
    cd "$src_dir"
    ./configure --prefix="${LOCAL_DEPS_DIR}" --disable-static >> "$log" 2>&1
    make -j"$(nproc 2>/dev/null || echo 2)"  >> "$log" 2>&1
    make install                              >> "$log" 2>&1
  ) || { echo "ERROR: SQLite build failed. Check $log" >&2; return 1; }
  rm -rf "$src_dir" "$tarball"
  echo "SQLite built successfully into ${LOCAL_DEPS_DIR}." >&2
}

_bootstrap_openssl() {
  local tarball="$HOME/.tmp/openssl-${OPENSSL_VERSION}.tar.gz"
  local src_dir="$HOME/.tmp/openssl-${OPENSSL_VERSION}"
  echo "Building OpenSSL ${OPENSSL_VERSION} from source (no sudo)..." >&2
  echo "(This can take up to 5 minutes.)" >&2
  mkdir -p "$HOME/.tmp" "${LOCAL_DEPS_DIR}"
  if [[ ! -f "$tarball" ]]; then
    curl -fsSL \
      "https://www.openssl.org/source/openssl-${OPENSSL_VERSION}.tar.gz" \
      -o "$tarball" >> "$log" 2>&1 \
      || { echo "ERROR: Failed to download OpenSSL tarball." >&2; return 1; }
  fi
  tar xf "$tarball" -C "$HOME/.tmp" >> "$log" 2>&1
  (
    cd "$src_dir"
    # install_sw skips man pages; no-shared keeps it self-contained
    ./config --prefix="${LOCAL_DEPS_DIR}" \
             --openssldir="${LOCAL_DEPS_DIR}/ssl" \
             no-shared >> "$log" 2>&1
    make -j"$(nproc 2>/dev/null || echo 2)" >> "$log" 2>&1
    make install_sw                          >> "$log" 2>&1
  ) || { echo "ERROR: OpenSSL build failed. Check $log" >&2; return 1; }
  rm -rf "$src_dir" "$tarball"
  echo "OpenSSL built successfully into ${LOCAL_DEPS_DIR}." >&2
}

# Ensures a known-good SQLite and (if headers are absent) OpenSSL are built
# into LOCAL_DEPS_DIR, then exports compiler/linker flags including an rpath
# so pyenv's Python and its _sqlite3.so always resolve to our libs at runtime.
bootstrap_local_deps() {
  local need_sqlite=0 need_openssl=0

  # SQLite: never trust the system version — check the actual .so for
  # sqlite3_deserialize (added 3.23.0). If our own build already exists and
  # passes, reuse it; otherwise build from source.
  local local_sqlite="${LOCAL_DEPS_DIR}/lib/libsqlite3.so"
  if sqlite_lib_ok "$local_sqlite"; then
    echo "Using existing local SQLite in ${LOCAL_DEPS_DIR}." >&2
  else
    local sys_sqlite
    sys_sqlite="$(find /usr/lib /lib -name "libsqlite3.so*" -not -type d 2>/dev/null | head -1)"
    if sqlite_lib_ok "$sys_sqlite"; then
      echo "System SQLite is new enough; using system headers." >&2
    else
      echo "System SQLite is too old (missing sqlite3_deserialize); will build from source." >&2
      need_sqlite=1
    fi
  fi

  # OpenSSL: only build if headers are genuinely absent.
  header_exists "openssl/ssl.h" || need_openssl=1

  if ! header_exists "zlib.h"; then
    echo "WARNING: zlib.h not found — Python zlib module may not build." >&2
  fi

  if [[ $need_sqlite -eq 1 || $need_openssl -eq 1 ]]; then
    require_command curl
    require_command make
    [[ $need_sqlite  -eq 1 ]] && { _bootstrap_sqlite  || return 1; }
    [[ $need_openssl -eq 1 ]] && { _bootstrap_openssl || return 1; }
  fi

  # Always wire in LOCAL_DEPS_DIR paths when our SQLite is present so the
  # rpath gets baked into _sqlite3.cpython-*.so at Python build time.
  if [[ -f "$local_sqlite" || $need_sqlite -eq 1 ]]; then
    export LDFLAGS="-L${LOCAL_DEPS_DIR}/lib -Wl,-rpath,${LOCAL_DEPS_DIR}/lib ${LDFLAGS:-}"
    export CPPFLAGS="-I${LOCAL_DEPS_DIR}/include ${CPPFLAGS:-}"
    export PKG_CONFIG_PATH="${LOCAL_DEPS_DIR}/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
    export LD_LIBRARY_PATH="${LOCAL_DEPS_DIR}/lib:${LD_LIBRARY_PATH:-}"
    echo "Local dep paths added to build environment (rpath: ${LOCAL_DEPS_DIR}/lib)." >&2
  fi

  if [[ $need_openssl -eq 1 ]]; then
    # OpenSSL was also built locally; add its paths if not already present
    export LDFLAGS="-L${LOCAL_DEPS_DIR}/lib ${LDFLAGS:-}"
    export CPPFLAGS="-I${LOCAL_DEPS_DIR}/include ${CPPFLAGS:-}"
  fi
}

# ── Build pyenv Python ────────────────────────────────────────────────────────

# Build (or rebuild) the pyenv Python with correct flags so sqlite3/ssl/zlib
# are compiled in. Called both on first install and when modules are missing.
build_pyenv_python() {
  local pyenv_cmd
  pyenv_cmd="$(pyenv_bin)"

  export PYENV_ROOT
  export PATH="${PYENV_ROOT}/bin:${PATH}"

  # Uninstall the broken build if it exists
  if "$pyenv_cmd" versions --bare 2>/dev/null | grep -Fxq "$PYENV_PYTHON_VERSION"; then
    echo "Removing existing pyenv Python ${PYENV_PYTHON_VERSION} (missing compiled modules)..." >&2
    "$pyenv_cmd" uninstall --force "$PYENV_PYTHON_VERSION" >> "$log" 2>&1
  fi

  echo "Building Python ${PYENV_PYTHON_VERSION} with sqlite3/ssl/zlib support..." >&2
  echo "(This can take up to 10 minutes — please do not close this terminal.)" >&2
  mkdir -p "$HOME/.tmp"
  export TMPDIR="$HOME/.tmp"
  export PYTHON_CONFIGURE_OPTS="--enable-loadable-sqlite-extensions"
  # Start with standard system paths
  export LDFLAGS="-L/usr/lib/x86_64-linux-gnu -L/usr/lib"
  export CPPFLAGS="-I/usr/include -I/usr/include/x86_64-linux-gnu"
  # Build any missing dev headers (sqlite3, openssl) locally if needed;
  # bootstrap_local_deps prepends LOCAL_DEPS_DIR paths to LDFLAGS/CPPFLAGS.
  bootstrap_local_deps || return 1

  if ! "$pyenv_cmd" install "$PYENV_PYTHON_VERSION" >> "$log" 2>&1; then
    echo "pyenv could not build Python ${PYENV_PYTHON_VERSION}." >&2
    echo "Check the log for details: $log" >&2
    echo "You can also try: PYTHON_BIN=python3.11 ./setup-hbd.sh" >&2
    return 1
  fi

  PYTHON_BIN="${PYENV_ROOT}/versions/${PYENV_PYTHON_VERSION}/bin/python3"
  echo "Python ${PYENV_PYTHON_VERSION} built successfully." >&2
}

ensure_pyenv_python() {
  if ! pyenv_available; then install_pyenv; fi

  export PYENV_ROOT
  export PATH="${PYENV_ROOT}/bin:${PATH}"

  local pyenv_cmd
  pyenv_cmd="$(pyenv_bin)"

  # Install if not present at all
  if ! "$pyenv_cmd" versions --bare 2>/dev/null | grep -Fxq "$PYENV_PYTHON_VERSION"; then
    build_pyenv_python || return 1
  fi

  PYTHON_BIN="${PYENV_ROOT}/versions/${PYENV_PYTHON_VERSION}/bin/python3"

  # Rebuild if the existing build is missing critical modules
  if ! python_modules_ok "$PYTHON_BIN"; then
    echo "Existing pyenv Python ${PYENV_PYTHON_VERSION} is missing compiled modules (sqlite3/ssl/zlib)." >&2
    echo "Rebuilding with correct flags..." >&2
    build_pyenv_python || return 1
    PYTHON_BIN="${PYENV_ROOT}/versions/${PYENV_PYTHON_VERSION}/bin/python3"

    # If it still fails after rebuild something is wrong with the host
    if ! python_modules_ok "$PYTHON_BIN"; then
      echo "ERROR: Python still missing modules after rebuild." >&2
      echo "The host may be missing libsqlite3-dev or libssl-dev system packages." >&2
      echo "Contact HBD support or try: PYTHON_BIN=python3.11 ./setup-hbd.sh" >&2
      return 1
    fi
  fi

  echo "Using pyenv-managed Python: ${PYTHON_BIN}" >&2
}

pick_python() {
  local candidates=() candidate="" found_old=()
  if [[ -n "${PYTHON_BIN}" ]]; then candidates+=("${PYTHON_BIN}"); fi
  candidates+=(python3.13 python3.12 python3.11 python3.10 python3.9 python3 python)

  for candidate in "${candidates[@]}"; do
    if ! command -v "$candidate" >/dev/null 2>&1; then continue; fi
    if python_version_ok "$candidate"; then
      # Also verify modules are intact for non-pyenv interpreters
      if python_modules_ok "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
      fi
      echo "Python at ${candidate} is missing compiled modules (sqlite3/ssl), skipping." >&2
    fi
    found_old+=("$candidate")
  done

  if [[ "${#found_old[@]}" -gt 0 ]]; then
    echo "Found Python interpreter(s), but none are usable: ${found_old[*]}" >&2
  else
    echo "No usable Python 3.9-3.13 found on PATH." >&2
  fi

  if [[ "$SKIP_PYENV_BOOTSTRAP" == "1" ]]; then
    echo "Rerun with e.g.: PYTHON_BIN=python3.11 ./setup-hbd.sh" >&2
    return 1
  fi

  ensure_pyenv_python || return 1
  printf '%s\n' "$PYTHON_BIN"
}

# ── Auth helpers ──────────────────────────────────────────────────────────────

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
      if ! is_public_bind "$BIND_ADDRESS"; then return 1; fi
      if [[ ! -t 0 ]]; then
        echo "Public bind detected but stdin is non-interactive — re-run in an interactive shell." >&2
        exit 1
      fi
      echo ""
      echo "This install is binding to ${BIND_ADDRESS} (public). Configuring built-in app auth."
      return 0
      ;;
    *)
      echo "Unknown AUTH_SETUP_MODE: ${AUTH_SETUP_MODE}" >&2; exit 1 ;;
  esac
}

upsert_env_value() {
  local key="$1" value="$2" file="$3" tmp_file
  tmp_file="$(mktemp)"
  awk -v key="$key" -v value="$value" '
    BEGIN { updated = 0 }
    index($0, key "=") == 1 { print key "=" value; updated = 1; next }
    { print }
    END { if (!updated) print key "=" value }
  ' "$file" > "$tmp_file"
  mv "$tmp_file" "$file"
}

build_password_hash() {
  local password="$1"
  "$VENV_PYTHON" - "$password" <<'PY'
import base64, hashlib, os, sys
password = sys.argv[1].encode("utf-8")
salt = os.urandom(16)
iterations = 390000
digest = hashlib.pbkdf2_hmac("sha256", password, salt, iterations)
print(
    f"pbkdf2_sha256${iterations}"
    f"${base64.b64encode(salt).decode('ascii')}"
    f"${base64.b64encode(digest).decode('ascii')}"
)
PY
}

setup_required_auth() {
  local user password password_confirm password_hash

  if ! should_setup_auth; then return 0; fi

  if [[ ! -f "$ENV_FILE" ]]; then
    [[ -f "$EXAMPLE_ENV_FILE" ]] && cp "$EXAMPLE_ENV_FILE" "$ENV_FILE" || : > "$ENV_FILE"
  fi

  user="$(whoami 2>/dev/null || id -un)"

  echo ""
  echo "Configuring required app auth for user ${user}..."
  echo "Use a strong password — this app is reachable on the public web."

  while true; do
    read -r -s -p "Please set a password for your app user ${user}> " password; echo ""
    read -r -s -p "Confirm password for ${user}> " password_confirm; echo ""

    if [[ -z "$password" ]];                     then echo "Password cannot be empty." >&2;                continue; fi
    if [[ "${#password}" -lt 8 ]];               then echo "Password must be at least 8 characters." >&2;  continue; fi
    if [[ "$password" == "$user" ]];             then echo "Password must not match the username." >&2;    continue; fi
    if [[ "$password" =~ [[:space:]] ]];         then echo "Password must not contain whitespace." >&2;    continue; fi
    if [[ "$password" != "$password_confirm" ]]; then echo "Passwords did not match. Try again." >&2;      continue; fi
    break
  done

  password_hash="$(build_password_hash "$password")"
  chmod 600 "$ENV_FILE" 2>/dev/null || true
  upsert_env_value "APP_AUTH_ENABLED"       "1"              "$ENV_FILE"
  upsert_env_value "APP_AUTH_USERNAME"      "$user"          "$ENV_FILE"
  upsert_env_value "APP_AUTH_PASSWORD_HASH" "$password_hash" "$ENV_FILE"

  unset password password_confirm password_hash
  echo "App auth configured for ${user} in ${ENV_FILE}."
}

# ── Install ───────────────────────────────────────────────────────────────────

function _install() {
    if [[ -f "$LOCK_FILE" ]]; then
        echo "${APP_NAME} is already installed. Use 'upgrade' or 'uninstall' first."
        exit 1
    fi

    require_command systemctl
    PYTHON_BIN="$(pick_python)"

    if [[ -z "$PORT" && -f "$PORT_FILE" ]]; then PORT="$(tr -d '[:space:]' < "$PORT_FILE")"; fi
    if [[ -z "$PORT" ]]; then PORT="$(port 10300 10500)"; fi
    if [[ ! "$PORT" =~ ^[0-9]+$ ]]; then echo "Port must be numeric." >&2; exit 1; fi

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
        echo "Existing virtualenv is not Python 3.9-3.13; recreating..."
        rm -rf "$VENV_DIR"
        "$PYTHON_BIN" -m venv "$VENV_DIR"
    fi

    VENV_PYTHON="${VENV_DIR}/bin/python"
    echo "Virtualenv Python: $(python_version_string "$VENV_PYTHON")"

    if [[ ! -f "$ENV_FILE" && -f "$EXAMPLE_ENV_FILE" ]]; then
        cp "$EXAMPLE_ENV_FILE" "$ENV_FILE"
        echo "Created ${ENV_FILE} from .env.example — fill in your Qobuz token before live matching."
    fi

    echo "Installing Python dependencies..."
    echo "(This can take a few minutes on first install.)"
    "${VENV_PYTHON}" -m pip install --upgrade pip >> "$log" 2>&1
    "${VENV_PYTHON}" -m pip install -r "${APP_DIR}/requirements.txt" 2>&1 | tee -a "$log"

    setup_required_auth

    local svc_type=simple
    if [[ $(systemctl --version | awk 'NR==1 {print $2}') -ge 240 ]]; then svc_type=exec; fi

    echo "Installing systemd service..."
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Bandcamp URL Filter Streamlit UI
After=syslog.target network.target

[Service]
Type=${svc_type}
WorkingDirectory=${APP_DIR}
Environment=HOME=${HOME}
Environment=PATH=${HOME}/.local/bin:${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONPATH=${APP_DIR}
Environment=XDG_CONFIG_HOME=${CONFIG_HOME}
Environment=STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
Environment=LD_LIBRARY_PATH=${LOCAL_DEPS_DIR}/lib
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
    is_public_bind "$BIND_ADDRESS" && \
        echo "Built-in app auth is enabled — login with your configured username/password."
    echo ""
    echo "Useful commands:"
    echo "  systemctl --user status  ${SERVICE_NAME}"
    echo "  journalctl --user -u ${SERVICE_NAME} -f"
    echo "  systemctl --user restart ${SERVICE_NAME}"
}

# ── Upgrade ───────────────────────────────────────────────────────────────────

function _upgrade() {
    if [[ ! -f "$LOCK_FILE" ]]; then echo "${APP_NAME} is not installed!"; exit 1; fi
    # shellcheck disable=SC1090
    source "$INSTALL_INFO"
    echo "Upgrading Python dependencies..."
    "${VENV_DIR}/bin/python" -m pip install --upgrade pip >> "$log" 2>&1
    "${VENV_DIR}/bin/python" -m pip install --upgrade -r "${APP_DIR}/requirements.txt" 2>&1 | tee -a "$log"
    systemctl --user try-restart "$SERVICE_NAME"
    echo "Upgrade complete."
}

# ── Uninstall ─────────────────────────────────────────────────────────────────

function _remove() {
    if [[ ! -f "$LOCK_FILE" ]]; then echo "${APP_NAME} is not installed!"; exit 1; fi
    systemctl --user stop    "$SERVICE_NAME" 2>/dev/null || true
    systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$SERVICE_FILE"
    systemctl --user daemon-reload
    rm -rf "$VENV_DIR" "$STATE_DIR"
    rm -f "$LOCK_FILE"
    echo "${APP_NAME} has been removed."
    echo "Your app files in ${APP_DIR} and .env were left intact."
}

# ── Entry point ───────────────────────────────────────────────────────────────

echo 'This is unsupported software. You will not get help with this, please answer `yes` if you understand and wish to proceed'
if [[ -z "${eula:-}" ]]; then read -r eula; fi
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
