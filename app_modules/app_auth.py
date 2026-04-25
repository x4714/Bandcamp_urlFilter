from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time

from app_modules.env_utils import env_flag, env_int


MIN_PBKDF2_SHA256_ITERATIONS = 390000
DEFAULT_AUTH_SESSION_TTL_SECONDS = 12 * 60 * 60
DEFAULT_AUTH_MAX_FAILURES = 5
DEFAULT_AUTH_LOCKOUT_SECONDS = 15 * 60
_AUTH_REMEMBER_ME_TTL = 30 * 24 * 60 * 60  # 30 days
_AUTH_COOKIE_NAME_DEFAULT = "bandcamp_urlfilter_auth_session"
_AUTH_COOKIE_STATE_KEY = "bandcamp_urlfilter_auth_cookie_sync"
_AUTH_DB_PATH = os.path.abspath(os.path.join(".streamlit", "bandcamp_urlfilter_auth.sqlite3"))
_AUTH_DB_TIMEOUT_SECONDS = 30.0
_AUTH_DB_BUSY_TIMEOUT_MS = 30_000
AUTH_COOKIE_SECURITY_WARNING = (
    "Known limitation: Streamlit can only sync this auth cookie from client-side JavaScript, "
    "so it cannot be marked HttpOnly. Treat it as a lightweight app gate, not a substitute "
    "for upstream auth at a reverse proxy or identity provider."
)

_AUTH_DB_LOCK = threading.Lock()


def _connect_auth_db() -> sqlite3.Connection:
    conn = sqlite3.connect(_AUTH_DB_PATH, timeout=_AUTH_DB_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {_AUTH_DB_BUSY_TIMEOUT_MS}")
    return conn


def _streamlit():
    import streamlit as st

    return st


def auth_enabled() -> bool:
    return env_flag("APP_AUTH_ENABLED", default=False)


def auth_username() -> str:
    return str(os.getenv("APP_AUTH_USERNAME", "")).strip()


def _stored_password_hash() -> str:
    return str(os.getenv("APP_AUTH_PASSWORD_HASH", "")).strip()


def auth_session_ttl_seconds() -> int:
    return env_int("APP_AUTH_SESSION_TTL_SECONDS", DEFAULT_AUTH_SESSION_TTL_SECONDS, minimum=60)


def auth_max_failures() -> int:
    return env_int("APP_AUTH_MAX_FAILURES", DEFAULT_AUTH_MAX_FAILURES, minimum=1)


def auth_lockout_seconds() -> int:
    return env_int("APP_AUTH_LOCKOUT_SECONDS", DEFAULT_AUTH_LOCKOUT_SECONDS, minimum=1)


def _auth_cookie_name() -> str:
    configured = str(os.getenv("APP_AUTH_COOKIE_NAME", "")).strip()
    if not configured:
        return _AUTH_COOKIE_NAME_DEFAULT
    sanitized = "".join(ch for ch in configured if ch.isalnum() or ch in {"-", "_"})
    return sanitized or _AUTH_COOKIE_NAME_DEFAULT


def _auth_cookie_secure() -> bool:
    return env_flag("APP_AUTH_COOKIE_SECURE", default=True)


def _ensure_auth_db() -> None:
    os.makedirs(os.path.dirname(_AUTH_DB_PATH), exist_ok=True)
    with _connect_auth_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                login_time REAL NOT NULL,
                remember INTEGER NOT NULL,
                expires REAL NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_state (
                scope TEXT PRIMARY KEY,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                lockout_until REAL NOT NULL DEFAULT 0.0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires ON auth_sessions (expires)"
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO auth_state(scope, failed_attempts, lockout_until)
            VALUES ('global', 0, 0.0)
            """
        )


def _get_auth_db_connection() -> sqlite3.Connection:
    _ensure_auth_db()
    return _connect_auth_db()


def _auth_token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _cleanup_expired_sessions(now: float | None = None) -> None:
    expires_before = time.time() if now is None else float(now)
    with _AUTH_DB_LOCK:
        with _get_auth_db_connection() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE expires <= ?", (expires_before,))


def _parse_password_hash(stored_hash: str) -> tuple[str, int, bytes, bytes]:
    algorithm, iterations_text, salt_b64, digest_b64 = stored_hash.split("$", 3)
    iterations = int(iterations_text)
    salt = base64.b64decode(salt_b64.encode("ascii"))
    expected = base64.b64decode(digest_b64.encode("ascii"))
    return algorithm, iterations, salt, expected


def validate_password_hash(stored_hash: str) -> str:
    try:
        algorithm, iterations, salt, expected = _parse_password_hash(stored_hash)
    except Exception:
        return "APP_AUTH_PASSWORD_HASH is malformed."

    if algorithm != "pbkdf2_sha256":
        return "APP_AUTH_PASSWORD_HASH must use pbkdf2_sha256."
    if iterations < MIN_PBKDF2_SHA256_ITERATIONS:
        return (
            "APP_AUTH_PASSWORD_HASH uses too few PBKDF2 iterations for public exposure. "
            "Re-run setup with a fresh password."
        )
    if len(salt) < 16:
        return "APP_AUTH_PASSWORD_HASH salt is too short."
    if len(expected) < 32:
        return "APP_AUTH_PASSWORD_HASH digest is too short."
    return ""


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = _parse_password_hash(stored_hash)
    except Exception:
        return False

    if algorithm != "pbkdf2_sha256" or iterations < MIN_PBKDF2_SHA256_ITERATIONS:
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(candidate, expected)


def _get_auth_state_row(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute(
        "SELECT failed_attempts, lockout_until FROM auth_state WHERE scope = 'global'"
    ).fetchone()
    if row is not None:
        return row
    conn.execute(
        """
        INSERT OR REPLACE INTO auth_state(scope, failed_attempts, lockout_until)
        VALUES ('global', 0, 0.0)
        """
    )
    return conn.execute(
        "SELECT failed_attempts, lockout_until FROM auth_state WHERE scope = 'global'"
    ).fetchone()


def _remaining_lockout_seconds(now: float | None = None) -> int:
    current_time = time.time() if now is None else float(now)
    with _AUTH_DB_LOCK:
        with _get_auth_db_connection() as conn:
            row = _get_auth_state_row(conn)
    lockout_until = float(row["lockout_until"] or 0.0)
    return max(0, int(lockout_until - current_time + 0.999))


def _register_failed_attempt(now: float | None = None) -> int:
    current_time = time.time() if now is None else float(now)
    with _AUTH_DB_LOCK:
        with _get_auth_db_connection() as conn:
            # Serialize failed-attempt updates so concurrent workers cannot lose increments.
            conn.execute("BEGIN IMMEDIATE")
            row = _get_auth_state_row(conn)
            lockout_until = float(row["lockout_until"] or 0.0)
            if lockout_until > current_time:
                return max(0, int(lockout_until - current_time + 0.999))

            failed_attempts = int(row["failed_attempts"] or 0) + 1
            next_lockout_until = 0.0
            if failed_attempts >= auth_max_failures():
                failed_attempts = 0
                next_lockout_until = current_time + auth_lockout_seconds()
            conn.execute(
                """
                UPDATE auth_state
                SET failed_attempts = ?, lockout_until = ?
                WHERE scope = 'global'
                """,
                (failed_attempts, next_lockout_until),
            )
    if next_lockout_until > current_time:
        return max(0, int(next_lockout_until - current_time + 0.999))
    return 0


def _clear_failed_attempts() -> None:
    with _AUTH_DB_LOCK:
        with _get_auth_db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE auth_state
                SET failed_attempts = 0, lockout_until = 0.0
                WHERE scope = 'global'
                """
            )


def _create_auth_token(username: str, login_time: float, remember: bool) -> tuple[str, int]:
    token = secrets.token_urlsafe(32)
    token_hash = _auth_token_hash(token)
    ttl = _AUTH_REMEMBER_ME_TTL if remember else auth_session_ttl_seconds()
    with _AUTH_DB_LOCK:
        with _get_auth_db_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO auth_sessions(token_hash, username, login_time, remember, expires, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    token_hash,
                    username,
                    float(login_time),
                    1 if remember else 0,
                    float(login_time + ttl),
                    float(login_time),
                ),
            )
    return token, ttl


def _validate_auth_token(token: str, configured_user: str, now: float) -> dict | None:
    if not token:
        return None
    _cleanup_expired_sessions(now)
    with _AUTH_DB_LOCK:
        with _get_auth_db_connection() as conn:
            row = conn.execute(
                """
                SELECT username, login_time, remember, expires
                FROM auth_sessions
                WHERE token_hash = ?
                """,
                (_auth_token_hash(token),),
            ).fetchone()
    if row is None:
        return None
    if str(row["username"] or "") != configured_user:
        return None
    if float(row["expires"] or 0.0) <= now:
        _revoke_auth_token(token)
        return None
    return {
        "username": str(row["username"] or ""),
        "login_time": float(row["login_time"] or 0.0),
        "remember": bool(row["remember"]),
        "expires": float(row["expires"] or 0.0),
    }


def _revoke_auth_token(token: str) -> None:
    if not token:
        return
    with _AUTH_DB_LOCK:
        with _get_auth_db_connection() as conn:
            conn.execute(
                "DELETE FROM auth_sessions WHERE token_hash = ?",
                (_auth_token_hash(token),),
            )


def _clear_auth_session_state() -> None:
    st = _streamlit()
    st.session_state.app_auth_authenticated = False
    st.session_state.app_auth_user = ""
    st.session_state.app_auth_login_time = 0.0
    st.session_state.app_auth_token = ""


def _queue_auth_cookie_sync(mode: str, token: str = "", max_age: int = 0) -> None:
    st = _streamlit()
    st.session_state[_AUTH_COOKIE_STATE_KEY] = {
        "mode": str(mode),
        "token": str(token),
        "max_age": int(max_age or 0),
    }


def _flush_auth_cookie_sync() -> None:
    st = _streamlit()
    pending = st.session_state.pop(_AUTH_COOKIE_STATE_KEY, None)
    if not isinstance(pending, dict):
        return

    mode = str(pending.get("mode", "")).strip().lower()
    if mode not in {"set", "clear"}:
        return

    # This cookie is set from browser-side JavaScript because Streamlit does not expose an
    # HTTP response hook here. That means the cookie cannot be marked HttpOnly.
    payload = {
        "cookieName": _auth_cookie_name(),
        "cookieValue": str(pending.get("token", "")),
        "maxAge": int(pending.get("max_age", 0) or 0),
        "mode": mode,
        "secure": _auth_cookie_secure(),
    }
    from app_modules.ui_js import run_inline_script

    run_inline_script(
        f"""
        <script>
        (function() {{
            const payload = {json.dumps(payload)};
            const parts = [
                `${{payload.cookieName}}=${{payload.mode === "clear" ? "" : encodeURIComponent(payload.cookieValue)}}`,
                "Path=/",
                "SameSite=Strict"
            ];
            if (payload.secure) {{
                parts.push("Secure");
            }}
            if (payload.mode === "clear") {{
                parts.push("Expires=Thu, 01 Jan 1970 00:00:00 GMT");
                parts.push("Max-Age=0");
            }} else if (payload.maxAge > 0) {{
                parts.push(`Max-Age=${{payload.maxAge}}`);
            }}
            document.cookie = parts.join("; ");
        }})();
        </script>
        """,
        height=0,
    )


def _request_auth_cookie_token() -> str:
    st = _streamlit()
    context = getattr(st, "context", None)
    cookies = getattr(context, "cookies", None) if context is not None else None
    if cookies is None:
        return ""
    return str(cookies.get(_auth_cookie_name(), "") or "").strip()


def _logout_session() -> None:
    st = _streamlit()
    auth_token = str(st.session_state.get("app_auth_token", "") or "")
    if not auth_token:
        auth_token = _request_auth_cookie_token()
    if auth_token:
        _revoke_auth_token(auth_token)
    _queue_auth_cookie_sync("clear")
    _clear_auth_session_state()


def _render_logout_button() -> None:
    st = _streamlit()
    configured_user = auth_username()
    with st.sidebar:
        st.caption(f"Signed in as `{configured_user}`")
        if st.button("Log out", key="app_auth_logout"):
            _logout_session()
            st.rerun()


def render_auth_gate() -> None:
    st = _streamlit()
    if not auth_enabled():
        return

    _flush_auth_cookie_sync()

    configured_user = auth_username()
    stored_hash = _stored_password_hash()
    if not configured_user or not stored_hash:
        st.error("App auth is enabled, but APP_AUTH_USERNAME or APP_AUTH_PASSWORD_HASH is missing.")
        st.stop()

    hash_error = validate_password_hash(stored_hash)
    if hash_error:
        st.error(hash_error)
        st.stop()

    now = time.time()

    login_time = float(st.session_state.get("app_auth_login_time", 0.0) or 0.0)
    if st.session_state.get("app_auth_authenticated") and st.session_state.get("app_auth_user") == configured_user:
        auth_token = str(st.session_state.get("app_auth_token", "") or "")
        if auth_token:
            if not _validate_auth_token(auth_token, configured_user, now):
                _logout_session()
                _flush_auth_cookie_sync()
                st.warning("Your sign-in expired. Please sign in again.")
                st.stop()
        elif login_time and now - login_time > auth_session_ttl_seconds():
            _logout_session()
            _flush_auth_cookie_sync()
            st.warning("Your sign-in expired. Please sign in again.")
            st.stop()
        _render_logout_button()
        return

    cookie_token = _request_auth_cookie_token()
    if cookie_token:
        token_data = _validate_auth_token(cookie_token, configured_user, now)
        if token_data:
            st.session_state.app_auth_authenticated = True
            st.session_state.app_auth_user = configured_user
            st.session_state.app_auth_login_time = float(token_data.get("login_time", now))
            st.session_state.app_auth_token = cookie_token
            _render_logout_button()
            return
        _queue_auth_cookie_sync("clear")
        _flush_auth_cookie_sync()

    st.title("Bandcamp to Qobuz Matcher")
    st.markdown("Sign in to access this app.")
    st.warning(AUTH_COOKIE_SECURITY_WARNING)
    remaining_lockout = _remaining_lockout_seconds(now)
    if remaining_lockout > 0:
        st.error(
            "Too many failed sign-in attempts. "
            f"Try again in about {remaining_lockout} seconds."
        )
    with st.form("app_auth_login_form", clear_on_submit=False):
        username = st.text_input("Username", value="")
        password = st.text_input("Password", value="", type="password")
        remember = st.checkbox(
            "Remember me",
            value=False,
            help="Keep me signed in for 30 days across browser sessions.",
        )
        submitted = st.form_submit_button("Sign in", use_container_width=True)

    if submitted:
        if remaining_lockout > 0:
            st.error(
                "Too many failed sign-in attempts. "
                f"Try again in about {remaining_lockout} seconds."
            )
            st.stop()
        user_ok = hmac.compare_digest(username.strip(), configured_user)
        password_ok = verify_password(password, stored_hash)
        if user_ok and password_ok:
            _clear_failed_attempts()
            token, ttl = _create_auth_token(configured_user, now, remember)
            st.session_state.app_auth_authenticated = True
            st.session_state.app_auth_user = configured_user
            st.session_state.app_auth_login_time = now
            st.session_state.app_auth_token = token
            _queue_auth_cookie_sync("set", token=token, max_age=ttl)
            st.rerun()
        lockout_seconds = _register_failed_attempt(now)
        if lockout_seconds > 0:
            st.error(
                "Too many failed sign-in attempts. "
                f"Try again in about {lockout_seconds} seconds."
            )
            st.stop()
        st.error("Invalid username or password.")

    st.stop()
