import base64
import hashlib
import hmac
import os
import secrets
import threading
import time

import streamlit as st


MIN_PBKDF2_SHA256_ITERATIONS = 390000
DEFAULT_AUTH_SESSION_TTL_SECONDS = 12 * 60 * 60
DEFAULT_AUTH_MAX_FAILURES = 5
DEFAULT_AUTH_LOCKOUT_SECONDS = 15 * 60
_AUTH_REMEMBER_ME_TTL = 30 * 24 * 60 * 60  # 30 days

_AUTH_STATE_LOCK = threading.Lock()
_AUTH_STATE: dict[str, float | int] = {
    "failed_attempts": 0,
    "lockout_until": 0.0,
}


@st.cache_resource(show_spinner=False)
def _get_auth_token_store() -> dict[str, dict]:
    # Process-level store: {token: {username, login_time, remember, expires}}
    return {}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def auth_enabled() -> bool:
    return _env_flag("APP_AUTH_ENABLED", default=False)


def auth_username() -> str:
    return str(os.getenv("APP_AUTH_USERNAME", "")).strip()


def _stored_password_hash() -> str:
    return str(os.getenv("APP_AUTH_PASSWORD_HASH", "")).strip()


def auth_session_ttl_seconds() -> int:
    return _env_int("APP_AUTH_SESSION_TTL_SECONDS", DEFAULT_AUTH_SESSION_TTL_SECONDS, minimum=60)


def auth_max_failures() -> int:
    return _env_int("APP_AUTH_MAX_FAILURES", DEFAULT_AUTH_MAX_FAILURES, minimum=1)


def auth_lockout_seconds() -> int:
    return _env_int("APP_AUTH_LOCKOUT_SECONDS", DEFAULT_AUTH_LOCKOUT_SECONDS, minimum=1)


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


def _remaining_lockout_seconds(now: float | None = None) -> int:
    current_time = time.time() if now is None else now
    with _AUTH_STATE_LOCK:
        lockout_until = float(_AUTH_STATE.get("lockout_until", 0.0) or 0.0)
    return max(0, int(lockout_until - current_time + 0.999))


def _register_failed_attempt(now: float | None = None) -> int:
    current_time = time.time() if now is None else now
    with _AUTH_STATE_LOCK:
        lockout_until = float(_AUTH_STATE.get("lockout_until", 0.0) or 0.0)
        if lockout_until > current_time:
            return max(0, int(lockout_until - current_time + 0.999))

        failed_attempts = int(_AUTH_STATE.get("failed_attempts", 0) or 0) + 1
        _AUTH_STATE["failed_attempts"] = failed_attempts
        if failed_attempts >= auth_max_failures():
            lockout_until = current_time + auth_lockout_seconds()
            _AUTH_STATE["failed_attempts"] = 0
            _AUTH_STATE["lockout_until"] = lockout_until
            return max(0, int(lockout_until - current_time + 0.999))
    return 0


def _clear_failed_attempts() -> None:
    with _AUTH_STATE_LOCK:
        _AUTH_STATE["failed_attempts"] = 0
        _AUTH_STATE["lockout_until"] = 0.0


def _create_auth_token(username: str, login_time: float, remember: bool) -> str:
    token = secrets.token_urlsafe(32)
    ttl = _AUTH_REMEMBER_ME_TTL if remember else auth_session_ttl_seconds()
    _get_auth_token_store()[token] = {
        "username": username,
        "login_time": login_time,
        "remember": remember,
        "expires": login_time + ttl,
    }
    return token


def _validate_auth_token(token: str, configured_user: str, now: float) -> dict | None:
    store = _get_auth_token_store()
    data = store.get(token)
    if not data:
        return None
    if data.get("username") != configured_user:
        return None
    if data.get("expires", 0) <= now:
        store.pop(token, None)
        return None
    return data


def _revoke_auth_token(token: str) -> None:
    _get_auth_token_store().pop(token, None)


def _logout_session() -> None:
    auth_token = str(st.session_state.get("app_auth_token", "") or "")
    if not auth_token:
        auth_token = str(st.query_params.get("_auth", "") or "")
    if auth_token:
        _revoke_auth_token(auth_token)
    try:
        del st.query_params["_auth"]
    except (KeyError, Exception):
        pass
    st.session_state.app_auth_authenticated = False
    st.session_state.app_auth_user = ""
    st.session_state.app_auth_login_time = 0.0
    st.session_state.app_auth_token = ""


def _render_logout_button() -> None:
    configured_user = auth_username()
    with st.sidebar:
        st.caption(f"Signed in as `{configured_user}`")
        if st.button("Log out", key="app_auth_logout"):
            _logout_session()
            st.rerun()


def render_auth_gate() -> None:
    if not auth_enabled():
        return

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

    # 1. Check existing session state (same browser tab, no refresh)
    login_time = float(st.session_state.get("app_auth_login_time", 0.0) or 0.0)
    if st.session_state.get("app_auth_authenticated") and st.session_state.get("app_auth_user") == configured_user:
        auth_token = str(st.session_state.get("app_auth_token", "") or "")
        if auth_token:
            if not _validate_auth_token(auth_token, configured_user, now):
                _logout_session()
                st.warning("Your sign-in expired. Please sign in again.")
                st.stop()
        elif login_time and now - login_time > auth_session_ttl_seconds():
            _logout_session()
            st.warning("Your sign-in expired. Please sign in again.")
            st.stop()
        _render_logout_button()
        return

    # 2. Check URL token (survives page reload; set on login)
    url_token = str(st.query_params.get("_auth", "") or "")
    if url_token:
        token_data = _validate_auth_token(url_token, configured_user, now)
        if token_data:
            st.session_state.app_auth_authenticated = True
            st.session_state.app_auth_user = configured_user
            st.session_state.app_auth_login_time = float(token_data.get("login_time", now))
            st.session_state.app_auth_token = url_token
            _render_logout_button()
            return
        # Token invalid/expired — clear it
        try:
            del st.query_params["_auth"]
        except (KeyError, Exception):
            pass

    # 3. Show login form
    st.title("Bandcamp to Qobuz Matcher")
    st.markdown("Sign in to access this app.")
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
        submitted = st.form_submit_button(
            "Sign in",
            use_container_width=True,
            disabled=remaining_lockout > 0,
        )

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
            token = _create_auth_token(configured_user, now, remember)
            st.session_state.app_auth_authenticated = True
            st.session_state.app_auth_user = configured_user
            st.session_state.app_auth_login_time = now
            st.session_state.app_auth_token = token
            st.query_params["_auth"] = token
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
