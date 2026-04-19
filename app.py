import os
import time
from datetime import datetime, timezone

import streamlit as st
from dotenv import load_dotenv
from app_modules.app_auth import render_auth_gate
from app_modules.debug_logging import emit_debug

from app_modules.filtering import validate_filters
from app_modules.streamrip import (
    CODEC_OPTIONS,
    QUALITY_OPTIONS,
    ensure_streamrip_config_file,
    fetch_qobuz_account_info,
    format_quality_option,
    get_default_downloads_folder,
    get_env_qobuz_values,
    get_streamrip_config_path,
    is_streamrip_installed,
    load_streamrip_settings,
    save_streamrip_settings,
)
from app_modules.system_utils import open_in_default_app
from app_modules.ui_processing import (
    handle_process_submission,
    render_results_and_exports,
    render_status_log,
    run_processing_tick,
)
from app_modules.ui_modal import (
    init_qobuz_help_state,
    open_qobuz_help_modal,
    render_modal_base_styles,
    render_qobuz_help_modals,
)
from app_modules.ui_smoked_salmon import render_smoked_salmon_tab
from app_modules.ui_state import init_session_state, remember_session_snapshot_value
from app_modules.ui_streamrip_setup import (
    init_streamrip_download_state,
    init_streamrip_form_state,
    render_streamrip_setup,
)
from app_modules.ui_tools import render_direct_qobuz_rip_tab

load_dotenv()

st.set_page_config(page_title="Bandcamp to Qobuz Matcher", layout="wide")
render_auth_gate()
st.title("🎵 Bandcamp to Qobuz Matcher")
st.markdown("Filter your Bandcamp URLs and find exact high-resolution matches on Qobuz.")
render_modal_base_styles()


def _app_debug(message: str) -> None:
    emit_debug("app", message)


def render_wip_notice() -> None:
    st.markdown(
        f"""
        <div style="
            margin: 0.4rem 0 1rem 0;
            padding: 0.9rem 1rem;
            border-radius: 10px;
            border: 1px solid rgba(255,255,255,0.18);
            background: linear-gradient(135deg, rgba(0,0,0,0.72), rgba(20,20,20,0.78));
            color: #f2f2f2;
            font-weight: 600;
            font-size: 3rem;
            text-align: center;
            letter-spacing: 0.2px;
        ">
            WIP 🚧
        </div>
        """,
        unsafe_allow_html=True,
    )


def _get_file_mtime_ns(path: str) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return -1


def _get_env_mtime_ns(env_path: str = ".env") -> int:
    return _get_file_mtime_ns(env_path)


def _sync_env_file_changes() -> None:
    current_mtime_ns = _get_env_mtime_ns(".env")
    previous_mtime_ns = st.session_state.get("_env_file_mtime_ns")
    if previous_mtime_ns is None:
        st.session_state._env_file_mtime_ns = current_mtime_ns
        return
    if current_mtime_ns != previous_mtime_ns:
        st.session_state._env_file_mtime_ns = current_mtime_ns
        load_dotenv(override=True)
        _app_debug("Detected .env file change; reloaded environment values.")


def _mount_env_watchdog() -> None:
    # Keep env sync deterministic and avoid background fragment rerun churn.
    _sync_env_file_changes()


def _render_alert_scroll_if_requested() -> None:
    if not st.session_state.get("auto_scroll_alerts_once", False):
        return
    st.iframe(
        """
        <script>
            const doc = window.parent.document;
            const alerts = doc.querySelectorAll('[data-testid="stAlert"]');
            if (alerts.length > 0) {
                alerts[0].scrollIntoView({ behavior: "smooth", block: "center" });
            } else {
                const root = doc.querySelector("section.main");
                if (root) {
                    root.scrollTo({ top: 0, behavior: "smooth" });
                } else {
                    window.parent.scrollTo({ top: 0, behavior: "smooth" });
                }
            }
        </script>
        """,
        height=1,
    )
    st.session_state.auto_scroll_alerts_once = False


init_session_state()
init_qobuz_help_state()
_mount_env_watchdog()

MAIN_TABS = [
    "Bandcamp Matcher",
    "Direct Qobuz Rip",
    "Smoked Salmon Upload",
    "Smoked Salmon Settings",
    "Qobuz Settings",
    "Streamrip Settings",
]


def _apply_pending_main_tab_redirect() -> None:
    pending_target = str(st.session_state.pop("main_tab_selection_pending", "")).strip()
    if pending_target and pending_target in MAIN_TABS:
        st.session_state.main_tab_selection = pending_target

st.markdown(
    """
<style>
.st-key-main_tab_selection [data-testid="stRadio"] > div {
  display: flex;
  gap: 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.16);
}
.st-key-main_tab_selection [data-baseweb="radio"] {
  margin-right: 0 !important;
  padding: 0.55rem 0.9rem 0.6rem 0.9rem;
  border-bottom: 2px solid transparent;
}
.st-key-main_tab_selection [data-baseweb="radio"] > div:first-child {
  display: none;
}
.st-key-main_tab_selection [data-baseweb="radio"] > div:last-child {
  font-weight: 600;
  opacity: 0.82;
}
.st-key-main_tab_selection [data-baseweb="radio"]:has(input:checked) {
  border-bottom-color: #ff4b4b !important;
}
.st-key-main_tab_selection [data-baseweb="radio"]:has(input:checked) > div:last-child {
  opacity: 1;
  color: inherit !important;
}
</style>
""",
    unsafe_allow_html=True,
)

_apply_pending_main_tab_redirect()

main_tab = st.radio(
    "Main Tab",
    options=MAIN_TABS,
    key="main_tab_selection",
    horizontal=True,
    label_visibility="collapsed",
)
_app_debug(f"Main tab selected: `{main_tab}`.")

tag_input = ""
exclude_tag_input = ""
location_input = ""
min_tracks = None
max_tracks = None
min_duration = None
max_duration = None
start_date = None
end_date = None
free_mode = "All"
dry_run = False

def _open_env_for_qobuz() -> None:
    env_path = ".env"
    if not os.path.exists(env_path):
        template = """# Important: So that Python recognizes local directories (e.g., logic) as modules
PYTHONPATH=.
# Optional: Set your own Qobuz App ID (if omitted, the app auto-fetches it from Qobuz Web Player)
# QOBUZ_APP_ID=
# Required (depending on region/account type): Set your user Auth Token for Qobuz
QOBUZ_USER_AUTH_TOKEN=
# Optional app login for public-facing deployments
APP_AUTH_ENABLED=0
APP_AUTH_USERNAME=
APP_AUTH_PASSWORD_HASH=
# Tracker API Keys or Session Cookies for duplicate checking
RED_API_KEY=
RED_SESSION_COOKIE=
OPS_API_KEY=
OPS_SESSION_COOKIE=
# Optional tracker base URLs if you do not use the defaults
# RED_URL=https://redacted.sh
# OPS_URL=https://orpheus.network"""
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(template)
        except Exception as e:
            _app_debug(f"Failed creating .env template file: {e}")
            st.session_state.auto_scroll_alerts_once = True
            st.error(f"Error creating the .env file: {e}")
            return

    try:
        open_in_default_app(env_path)
        _app_debug("Opened .env in default app.")
    except Exception as e:
        _app_debug(f"Failed opening .env in default app: {e}")
        st.session_state.auto_scroll_alerts_once = True
        st.error(f"Could not open .env: {e}")


if main_tab == "Bandcamp Matcher":
    st.sidebar.header("Configuration")
    _app_debug("Sidebar: Configuration header rendered.")
    _app_debug("Sidebar: rendering matcher filter/date/run settings.")
    with st.sidebar.expander("🎯 Matcher Filter Rules", expanded=False):
        tag_input = st.text_input("Include Genre / Tag", value="", help="Filter by tag or genre. Separate multiple with commas (e.g. 'rock, jazz').")
        exclude_tag_input = st.text_input("Exclude Genre / Tag", value="", help="Exclude tags or genres. Separate multiple with commas.")
        location_input = st.text_input("Location", value="", help="Filter by location text in metadata.")
        min_tracks = st.number_input("Min Tracks", min_value=1, value=None, step=1, help="Leave empty for no minimum.")
        max_tracks = st.number_input("Max Tracks", min_value=1, value=None, step=1, help="Leave empty for no maximum.")
        min_duration = st.number_input("Min Duration (min)", min_value=1, value=None, step=1, help="Leave empty for no minimum.")
        max_duration = st.number_input("Max Duration (min)", min_value=1, value=None, step=1, help="Leave empty for no maximum.")

    with st.sidebar.expander("📅 Matcher Release Date Filter", expanded=False):
        start_date = st.date_input("Start Date", value=None, help="Filter for releases on or after this date.")
        end_date = st.date_input("End Date", value=None, help="Filter for releases on or before this date.")

    with st.sidebar.expander("⚙️ Matcher Run Settings", expanded=True):
        free_mode = st.selectbox("Pricing", options=["All", "Free", "Paid"], index=0, help="Filter releases by Bandcamp pricing type.")
        dry_run = st.checkbox("Dry Run", value=False, help="Only apply Bandcamp filter, skip Qobuz search.")
        red_key = os.getenv("RED_API_KEY", "")
        ops_key = os.getenv("OPS_API_KEY", "")
        check_red = False
        check_ops = False
        if red_key:
            check_red = st.checkbox("Check RED", value=False, help="Check Qobuz matches against Redacted (RED) for duplicates.")
        if ops_key:
            check_ops = st.checkbox("Check OPS", value=False, help="Check Qobuz matches against Orpheus (OPS) for duplicates.")

if main_tab in {"Qobuz Settings", "Streamrip Settings", "Smoked Salmon Settings"}:
    st.sidebar.header("Configuration")
    _app_debug("Sidebar: Configuration header rendered for settings tab.")
    with st.sidebar.expander("⚙️ Settings Navigation", expanded=True):
        st.caption("Quickly jump between settings pages.")
        if st.button("Open Qobuz Settings", key="sidebar_open_qobuz_settings"):
            st.session_state.main_tab_selection_pending = "Qobuz Settings"
            st.rerun()
        if st.button("Open Streamrip Settings", key="sidebar_open_streamrip_settings"):
            st.session_state.main_tab_selection_pending = "Streamrip Settings"
            st.rerun()
        if st.button("Open Smoked Salmon Settings", key="sidebar_open_smoked_settings"):
            st.session_state.main_tab_selection_pending = "Smoked Salmon Settings"
            st.rerun()

    with st.sidebar.expander("🛠️ Tracker Debugger", expanded=False):
        st.caption("Manually test duplicate checks for RED/OPS.")
        dbg_artist = st.text_input("Test Artist", key="dbg_art")
        dbg_album = st.text_input("Test Album", key="dbg_alb")
        dbg_upc = st.text_input("Test UPC (Optional)", key="dbg_upc")
        
        if st.button("Run Diagnostic Check", use_container_width=True):
            if not dbg_artist or not dbg_album:
                st.warning("Please enter at least Artist and Album.")
            else:
                from app_modules.ui_processing import run_tracker_diagnostic
                run_tracker_diagnostic(dbg_artist, dbg_album, dbg_upc)

render_qobuz_help_modals()

def _load_streamrip_runtime_state(
    status_callback=None,
) -> tuple[str, bool, str, dict, str, str, str]:
    _app_debug("Loading streamrip runtime state.")
    if status_callback:
        status_callback("Resolving Streamrip config path...")
    config_path = get_streamrip_config_path()

    if status_callback:
        status_callback("Checking Streamrip config file...")
    config_ready, config_init_msg = ensure_streamrip_config_file(config_path)

    settings = {}
    settings_error = ""
    if config_ready:
        if status_callback:
            status_callback("Loading Streamrip settings from config.toml...")
        settings, settings_error = load_streamrip_settings(config_path)

    if status_callback:
        status_callback("Reading .env and resolving Qobuz token/App ID...")
    qobuz_app_id, qobuz_token = get_env_qobuz_values(
        status_callback=status_callback,
        fallback_app_id=str(settings.get("app_id", "")).strip(),
    )
    _app_debug(
        "Streamrip runtime state loaded "
        f"(config_ready={config_ready}, settings_loaded={bool(settings)}, "
        f"app_id_present={bool(qobuz_app_id)}, token_present={bool(qobuz_token)})."
    )
    return (
        config_path,
        config_ready,
        config_init_msg,
        settings,
        settings_error,
        qobuz_app_id,
        qobuz_token,
    )


def _make_streamrip_boot_status_callback(streamrip_boot_status):
    # Throttle very chatty discovery updates so the status label stays readable.
    last = {"message": "", "emit_at": 0.0}

    def _update(message: str) -> None:
        text = str(message or "").strip()
        if not text:
            return
        now = time.monotonic()
        if text == last["message"] and (now - float(last["emit_at"])) < 1.0:
            return
        if (now - float(last["emit_at"])) < 0.2:
            return
        last["message"] = text
        last["emit_at"] = now
        streamrip_boot_status.update(label=f"Streamrip setup: {text}", state="running")

    return _update


@st.cache_data(show_spinner=False)
def _load_streamrip_runtime_state_cached(
    env_mtime_ns: int,
    config_path_hint: str,
    config_mtime_ns: int,
    _status_callback=None,
) -> tuple[str, bool, str, dict, str, str, str]:
    # Cache key is fully represented by function args; values are intentionally unused.
    _ = (env_mtime_ns, config_path_hint, config_mtime_ns)
    _app_debug("Loading streamrip runtime state via process cache.")
    return _load_streamrip_runtime_state(status_callback=_status_callback)


@st.cache_resource
def _streamrip_runtime_snapshot_store() -> dict:
    return {"key": None, "state": None, "config_path_hint": ""}


def _snapshot_streamrip_runtime_state(
    env_mtime_ns: int,
    config_mtime_ns: int,
    state: tuple[str, bool, str, dict, str, str, str],
) -> None:
    store = _streamrip_runtime_snapshot_store()
    store["key"] = (int(env_mtime_ns), int(config_mtime_ns))
    store["state"] = state
    store["config_path_hint"] = str(state[0] or "")


def _read_streamrip_runtime_snapshot(
    env_mtime_ns: int,
    config_mtime_ns: int,
) -> tuple[str, bool, str, dict, str, str, str] | None:
    store = _streamrip_runtime_snapshot_store()
    if store.get("key") != (int(env_mtime_ns), int(config_mtime_ns)):
        return None
    state = store.get("state")
    if isinstance(state, tuple) and len(state) == 7:
        return state
    return None


def _get_streamrip_config_path_hint() -> str:
    store = _streamrip_runtime_snapshot_store()
    hint = str(store.get("config_path_hint", "")).strip()
    return hint


def _cache_streamrip_runtime_state(
    config_path: str,
    config_ready: bool,
    config_init_msg: str,
    settings: dict,
    settings_error: str,
    qobuz_app_id: str,
    qobuz_token: str,
) -> None:
    st.session_state.streamrip_runtime_state = {
        "config_path": config_path,
        "config_ready": bool(config_ready),
        "config_init_msg": str(config_init_msg or ""),
        "settings": dict(settings or {}),
        "settings_error": str(settings_error or ""),
        "qobuz_app_id": str(qobuz_app_id or ""),
        "qobuz_token": str(qobuz_token or ""),
        "env_mtime_ns": _get_env_mtime_ns(".env"),
        "config_mtime_ns": _get_file_mtime_ns(config_path),
    }
    remember_session_snapshot_value("streamrip_runtime_state", st.session_state.streamrip_runtime_state)
    _snapshot_streamrip_runtime_state(
        st.session_state.streamrip_runtime_state["env_mtime_ns"],
        st.session_state.streamrip_runtime_state["config_mtime_ns"],
        (
            config_path,
            bool(config_ready),
            str(config_init_msg or ""),
            dict(settings or {}),
            str(settings_error or ""),
            str(qobuz_app_id or ""),
            str(qobuz_token or ""),
        ),
    )


def _streamrip_runtime_cache_is_stale(cache: dict) -> bool:
    def _safe_int(value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    config_path = str(cache.get("config_path", "")).strip()
    if not config_path:
        return True
    current_env_mtime = _get_env_mtime_ns(".env")
    current_config_mtime = _get_file_mtime_ns(config_path)
    cached_env_mtime = _safe_int(cache.get("env_mtime_ns", -2), -2)
    cached_config_mtime = _safe_int(cache.get("config_mtime_ns", -2), -2)
    return (cached_env_mtime != current_env_mtime) or (cached_config_mtime != current_config_mtime)


def _parse_utc_datetime(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidates = [raw]
    if raw.endswith("Z"):
        candidates.append(f"{raw[:-1]}+00:00")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _qobuz_account_days_until_expiry(expires_at_iso: str) -> int | None:
    expires_at = _parse_utc_datetime(expires_at_iso)
    if expires_at is None:
        return None
    seconds_left = (expires_at - datetime.now(timezone.utc)).total_seconds()
    return int(seconds_left // 86400)


def _token_fingerprint(token: str) -> str:
    token = str(token or "")
    if not token:
        return ""
    return f"{len(token)}:{token[-6:]}"


def _pick_streamrip_identifier_from_account(account_data: dict, fallback: str = "") -> str:
    if not isinstance(account_data, dict):
        return str(fallback or "").strip()
    for key in ("user_id", "identifier", "login", "email"):
        candidate = str(account_data.get(key, "")).strip()
        if candidate:
            return candidate
    return str(fallback or "").strip()


def _should_refresh_qobuz_account_info(cache: dict, app_id: str, token: str) -> bool:
    if not isinstance(cache, dict) or not cache:
        return True
    if str(cache.get("app_id", "")) != str(app_id):
        return True
    if str(cache.get("token_fingerprint", "")) != _token_fingerprint(token):
        return True

    fetched_at = _parse_utc_datetime(str(cache.get("fetched_at", "")))
    if fetched_at is None:
        return True

    ok = bool(cache.get("ok", False))
    today = datetime.now(timezone.utc).date()
    if not ok:
        return fetched_at.date() != today

    days_left = _qobuz_account_days_until_expiry(str(cache.get("subscription_expires_at", "")))
    if days_left is None:
        return False
    if days_left > 7:
        return False
    return fetched_at.date() != today


cached_streamrip_state = st.session_state.get("streamrip_runtime_state")

if not isinstance(cached_streamrip_state, dict):
    _app_debug("Initial streamrip boot load path entered.")
    initial_config_path = _get_streamrip_config_path_hint() or get_streamrip_config_path()
    env_mtime_ns = _get_env_mtime_ns(".env")
    config_mtime_ns = _get_file_mtime_ns(initial_config_path)
    with st.status("Starting Streamrip setup...", expanded=False) as streamrip_boot_status:
        streamrip_boot_status.update(label="Resolving Streamrip runtime state...", state="running")
        boot_status_callback = _make_streamrip_boot_status_callback(streamrip_boot_status)
        cached_snapshot = _read_streamrip_runtime_snapshot(env_mtime_ns, config_mtime_ns)
        if cached_snapshot is not None:
            _app_debug("Restoring streamrip runtime state from snapshot cache.")
            streamrip_boot_status.update(label="Restoring Streamrip runtime state from cache...", state="running")
            (
                streamrip_config_path,
                streamrip_config_ready,
                streamrip_config_init_msg,
                streamrip_settings,
                streamrip_settings_error,
                env_qobuz_app_id,
                env_qobuz_token,
            ) = cached_snapshot
        else:
            (
                streamrip_config_path,
                streamrip_config_ready,
                streamrip_config_init_msg,
                streamrip_settings,
                streamrip_settings_error,
                env_qobuz_app_id,
                env_qobuz_token,
            ) = _load_streamrip_runtime_state_cached(
                env_mtime_ns,
                initial_config_path,
                config_mtime_ns,
                _status_callback=boot_status_callback,
            )
        streamrip_boot_status.update(label="Streamrip setup ready.", state="complete")
    _cache_streamrip_runtime_state(
        streamrip_config_path,
        streamrip_config_ready,
        streamrip_config_init_msg,
        streamrip_settings,
        streamrip_settings_error,
        env_qobuz_app_id,
        env_qobuz_token,
    )
else:
    if _streamrip_runtime_cache_is_stale(cached_streamrip_state):
        _app_debug("Streamrip runtime cache stale; refreshing runtime state.")
        (
            streamrip_config_path,
            streamrip_config_ready,
            streamrip_config_init_msg,
            streamrip_settings,
            streamrip_settings_error,
            env_qobuz_app_id,
            env_qobuz_token,
        ) = _load_streamrip_runtime_state()
        _cache_streamrip_runtime_state(
            streamrip_config_path,
            streamrip_config_ready,
            streamrip_config_init_msg,
            streamrip_settings,
            streamrip_settings_error,
            env_qobuz_app_id,
            env_qobuz_token,
        )
    else:
        _app_debug("Using cached streamrip runtime state.")
        streamrip_config_path = str(cached_streamrip_state.get("config_path", ""))
        streamrip_config_ready = bool(cached_streamrip_state.get("config_ready", False))
        streamrip_config_init_msg = str(cached_streamrip_state.get("config_init_msg", ""))
        streamrip_settings = dict(cached_streamrip_state.get("settings", {}) or {})
        streamrip_settings_error = str(cached_streamrip_state.get("settings_error", ""))
        env_qobuz_app_id = str(cached_streamrip_state.get("qobuz_app_id", ""))
        env_qobuz_token = str(cached_streamrip_state.get("qobuz_token", ""))

if streamrip_config_ready and streamrip_settings:
    current_streamrip_token = str(streamrip_settings.get("password_or_token", "")).strip()
    current_streamrip_app_id = str(streamrip_settings.get("app_id", "")).strip()
    current_streamrip_identifier = str(streamrip_settings.get("email_or_userid", "")).strip()
    active_qobuz_app_id = current_streamrip_app_id or str(env_qobuz_app_id or "").strip()

    env_mtime_ns = _get_env_mtime_ns(".env")
    config_mtime_ns = _get_file_mtime_ns(streamrip_config_path)
    env_token_newer_than_streamrip = bool(
        str(env_qobuz_token or "").strip()
        and str(env_qobuz_token or "").strip() != current_streamrip_token
        and env_mtime_ns > config_mtime_ns
    )
    env_sync_marker = (
        f"{env_mtime_ns}:{_token_fingerprint(env_qobuz_token)}:{_token_fingerprint(active_qobuz_app_id)}"
    )
    env_sync_marker_key = "qobuz_env_token_sync_marker"
    already_processed_marker = str(st.session_state.get(env_sync_marker_key, ""))
    should_attempt_env_sync = env_token_newer_than_streamrip and (already_processed_marker != env_sync_marker)

    if should_attempt_env_sync:
        _app_debug("Detected newer .env token than streamrip config; validating and auto-filling from /user/login.")
        st.session_state[env_sync_marker_key] = env_sync_marker
        remember_session_snapshot_value(env_sync_marker_key, env_sync_marker)
        if not active_qobuz_app_id:
            _app_debug("Skipped newer env token sync because no app ID is available.")
        else:
            ok_info, info_data, info_msg = fetch_qobuz_account_info(active_qobuz_app_id, env_qobuz_token)
            if ok_info:
                resolved_identifier = _pick_streamrip_identifier_from_account(info_data, current_streamrip_identifier)
                save_ok, save_msg = save_streamrip_settings(
                    streamrip_config_path,
                    use_auth_token=True,
                    email_or_userid=resolved_identifier,
                    password_or_token=env_qobuz_token,
                    app_id=active_qobuz_app_id,
                    quality=int(streamrip_settings.get("quality", 3)),
                    codec_selection=str(streamrip_settings.get("codec_selection", "Original")),
                    downloads_folder=str(streamrip_settings.get("downloads_folder", "")),
                    downloads_db_path=str(streamrip_settings.get("downloads_db_path", "")),
                    failed_downloads_path=str(streamrip_settings.get("failed_downloads_path", "")),
                )
                if save_ok:
                    _app_debug("Newer env token sync succeeded; streamrip credentials auto-filled from Qobuz login payload.")
                    st.session_state.qobuz_autofill_notice = (
                        "Detected a newer token in `.env`. Verified it with Qobuz and auto-filled Streamrip "
                        f"credentials (token, App ID, identifier: `{resolved_identifier}`)."
                    )
                    remember_session_snapshot_value("qobuz_autofill_notice", st.session_state.qobuz_autofill_notice)
                    normalized_cache = {
                        "ok": True,
                        "message": str(info_msg or ""),
                        "app_id": str(active_qobuz_app_id),
                        "token_fingerprint": _token_fingerprint(env_qobuz_token),
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "data": dict(info_data or {}),
                        "subscription_expires_at": str(info_data.get("subscription_expires_at", "")),
                    }
                    st.session_state["qobuz_account_info_cache"] = normalized_cache
                    remember_session_snapshot_value("qobuz_account_info_cache", normalized_cache)
                    streamrip_settings, streamrip_settings_error = load_streamrip_settings(streamrip_config_path)
                    _cache_streamrip_runtime_state(
                        streamrip_config_path,
                        streamrip_config_ready,
                        streamrip_config_init_msg,
                        streamrip_settings,
                        streamrip_settings_error,
                        env_qobuz_app_id,
                        env_qobuz_token,
                    )
                else:
                    _app_debug(f"Newer env token sync save failed: {save_msg}")
            else:
                _app_debug(f"Newer env token validation failed; streamrip config not changed. reason={info_msg}")

if main_tab in {"Bandcamp Matcher", "Direct Qobuz Rip"}:
    if streamrip_config_init_msg:
        _app_debug(f"Sidebar info shown: {streamrip_config_init_msg}")
        st.sidebar.info(streamrip_config_init_msg)
    if streamrip_settings_error:
        _app_debug(f"Sidebar warning shown: {streamrip_settings_error}")
        st.sidebar.warning(streamrip_settings_error)

default_rip_quality = int(streamrip_settings.get("quality", 3)) if streamrip_settings else 3
if default_rip_quality not in QUALITY_OPTIONS:
    default_rip_quality = 3

default_codec = str(streamrip_settings.get("codec_selection", "Original")) if streamrip_settings else "Original"
if default_codec not in CODEC_OPTIONS:
    default_codec = "Original"

default_downloads_folder = str(streamrip_settings.get("downloads_folder", "") or get_default_downloads_folder()).strip()
init_streamrip_download_state(default_downloads_folder)
init_streamrip_form_state(
    streamrip_settings=streamrip_settings,
    default_rip_quality=default_rip_quality,
    default_codec=default_codec,
    streamrip_config_path=streamrip_config_path,
)

if "active_rip_quality" not in st.session_state or st.session_state.active_rip_quality not in QUALITY_OPTIONS:
    st.session_state.active_rip_quality = default_rip_quality
if "active_rip_codec" not in st.session_state or st.session_state.active_rip_codec not in CODEC_OPTIONS:
    st.session_state.active_rip_codec = default_codec
rip_quality = int(st.session_state.active_rip_quality)
rip_codec = str(st.session_state.active_rip_codec)

matcher_wip = bool(st.session_state.get("wip_matcher", False))
direct_rip_wip = bool(st.session_state.get("wip_direct_rip", False))
smoked_salmon_wip = bool(st.session_state.get("wip_smoked_salmon", True))
if main_tab in {"Bandcamp Matcher", "Direct Qobuz Rip", "Smoked Salmon Upload", "Smoked Salmon Settings"}:
    with st.sidebar.expander("🚧 WIP Toggles", expanded=False):
        _app_debug("Sidebar: rendering WIP Toggles section.")
        st.caption("Enable WIP lock for the active tab.")
        if main_tab == "Bandcamp Matcher":
            matcher_wip = st.toggle("Bandcamp Matcher WIP", value=matcher_wip, key="wip_matcher", help="Lock controls in this tab while work is in progress.")
            _app_debug(f"WIP toggle state (matcher): {matcher_wip}")
        elif main_tab == "Direct Qobuz Rip":
            direct_rip_wip = st.toggle("Direct Qobuz Rip WIP", value=direct_rip_wip, key="wip_direct_rip", help="Lock controls in this tab while work is in progress.")
            _app_debug(f"WIP toggle state (direct rip): {direct_rip_wip}")
        else:
            smoked_salmon_wip = st.toggle("Smoked Salmon Upload WIP", value=smoked_salmon_wip, key="wip_smoked_salmon", help="Lock controls in this tab while work is in progress.")
            _app_debug(f"WIP toggle state (smoked salmon): {smoked_salmon_wip}")

has_streamrip_identifier = bool(str(streamrip_settings.get("email_or_userid", "")).strip())
has_streamrip_token = bool(str(streamrip_settings.get("password_or_token", "")).strip())
has_streamrip_downloads_folder = bool(str(streamrip_settings.get("downloads_folder", "")).strip())
has_streamrip_downloads_db_path = bool(str(streamrip_settings.get("downloads_db_path", "")).strip())
has_streamrip_failed_downloads_path = bool(str(streamrip_settings.get("failed_downloads_path", "")).strip())
streamrip_missing_required_fields = []
if not has_streamrip_identifier:
    streamrip_missing_required_fields.append("email_or_userid")
if not has_streamrip_token:
    streamrip_missing_required_fields.append("password_or_token")
if not has_streamrip_downloads_folder:
    streamrip_missing_required_fields.append("downloads_folder")
if not has_streamrip_downloads_db_path:
    streamrip_missing_required_fields.append("downloads_db_path")
if not has_streamrip_failed_downloads_path:
    streamrip_missing_required_fields.append("failed_downloads_path")
streamrip_needs_setup = (
    not streamrip_config_ready
    or not streamrip_settings
    or not (
        has_streamrip_identifier
        and has_streamrip_token
        and has_streamrip_downloads_folder
        and has_streamrip_downloads_db_path
        and has_streamrip_failed_downloads_path
    )
)
_app_debug(f"Computed streamrip_needs_setup={streamrip_needs_setup}.")

autofill_notice = str(st.session_state.pop("qobuz_autofill_notice", "")).strip()
if autofill_notice:
    st.success(autofill_notice)

if "streamrip_setup_matcher_expand_once" not in st.session_state:
    st.session_state.streamrip_setup_matcher_expand_once = False
if "streamrip_setup_matcher_scroll_once" not in st.session_state:
    st.session_state.streamrip_setup_matcher_scroll_once = False
if "streamrip_setup_attention_message" not in st.session_state:
    st.session_state.streamrip_setup_attention_message = ""

if main_tab == "Qobuz Settings":
    st.subheader("🔐 Qobuz Settings")
    st.caption("Manage Qobuz auth and view account/subscription details.")

    configured_streamrip_app_id = str(streamrip_settings.get("app_id", "")).strip()
    active_qobuz_app_id = configured_streamrip_app_id or str(env_qobuz_app_id or "").strip()
    token_present = bool(str(env_qobuz_token or "").strip())
    env_app_id_present = bool(str(os.getenv("QOBUZ_APP_ID", "")).strip())

    if token_present:
        st.success("`QOBUZ_USER_AUTH_TOKEN` is available.")
    else:
        st.warning("`QOBUZ_USER_AUTH_TOKEN` is missing in `.env`.")

    if configured_streamrip_app_id:
        st.info("Using Qobuz App ID saved in Streamrip settings.")
    elif env_app_id_present:
        st.info("Using Qobuz App ID from `.env`.")
    elif active_qobuz_app_id:
        st.info("Using auto-discovered Qobuz App ID.")
    else:
        st.warning("No Qobuz App ID available yet. Save one below or enable auto-discovery.")

    with st.form("qobuz_app_id_form"):
        qobuz_app_id_input = st.text_input(
            "Qobuz App ID",
            value=active_qobuz_app_id,
            help="Saved into Streamrip settings so `.env` App ID is optional.",
        )
        save_qobuz_app_id = st.form_submit_button("Save App ID To Streamrip Settings")
    if save_qobuz_app_id:
        if not streamrip_config_ready:
            st.error("Streamrip config is not ready yet. Open Streamrip Settings and initialize it first.")
        else:
            ok_save, msg_save = save_streamrip_settings(
                streamrip_config_path,
                use_auth_token=bool(streamrip_settings.get("use_auth_token", True)),
                email_or_userid=str(streamrip_settings.get("email_or_userid", "")),
                password_or_token=str(streamrip_settings.get("password_or_token", "")).strip() or str(env_qobuz_token or ""),
                app_id=str(qobuz_app_id_input or "").strip(),
                quality=int(streamrip_settings.get("quality", default_rip_quality)),
                codec_selection=str(streamrip_settings.get("codec_selection", default_codec)),
                downloads_folder=str(streamrip_settings.get("downloads_folder", "")).strip() or default_downloads_folder,
                downloads_db_path=str(streamrip_settings.get("downloads_db_path", "")),
                failed_downloads_path=str(streamrip_settings.get("failed_downloads_path", "")),
            )
            if ok_save:
                _app_debug("Qobuz settings: saved app ID to streamrip config.")
                st.success("Saved Qobuz App ID to Streamrip settings.")
                st.rerun()
            else:
                st.error(msg_save)

    q_col1, q_col2, q_col3 = st.columns([1, 1, 1])
    with q_col1:
        if st.button("📝 Open .env for Qobuz Token", help="Open `.env` to set/update Qobuz token values."):
            _app_debug("Qobuz settings action: Open .env clicked.")
            _open_env_for_qobuz()
    with q_col2:
        if st.button("Get Qobuz Token", help="Open the built-in token help modal with step-by-step instructions."):
            _app_debug("Qobuz settings action: Get token help clicked.")
            open_qobuz_help_modal()
    with q_col3:
        refresh_account_info = st.button(
            "Refresh Account Info",
            help="Fetch latest account data now from Qobuz.",
        )

    cache_key = "qobuz_account_info_cache"
    if cache_key not in st.session_state:
        st.session_state[cache_key] = {}
    account_cache = dict(st.session_state.get(cache_key) or {})

    can_fetch_account_info = bool(active_qobuz_app_id and env_qobuz_token)
    if can_fetch_account_info and (
        refresh_account_info or _should_refresh_qobuz_account_info(account_cache, active_qobuz_app_id, env_qobuz_token)
    ):
        with st.spinner("Fetching Qobuz account details..."):
            ok_info, info_data, info_msg = fetch_qobuz_account_info(active_qobuz_app_id, env_qobuz_token)
        normalized_cache = {
            "ok": bool(ok_info),
            "message": str(info_msg or ""),
            "app_id": str(active_qobuz_app_id),
            "token_fingerprint": _token_fingerprint(env_qobuz_token),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data": dict(info_data or {}),
            "subscription_expires_at": str(info_data.get("subscription_expires_at", "")) if isinstance(info_data, dict) else "",
        }
        st.session_state[cache_key] = normalized_cache
        remember_session_snapshot_value(cache_key, normalized_cache)
        account_cache = normalized_cache
        if ok_info and streamrip_config_ready and streamrip_settings:
            current_streamrip_token = str(streamrip_settings.get("password_or_token", "")).strip()
            current_streamrip_identifier = str(streamrip_settings.get("email_or_userid", "")).strip()
            resolved_identifier = _pick_streamrip_identifier_from_account(info_data, current_streamrip_identifier)
            should_sync_to_streamrip = (
                current_streamrip_token != str(env_qobuz_token or "").strip()
                or (resolved_identifier and resolved_identifier != current_streamrip_identifier)
            )
            if should_sync_to_streamrip:
                sync_ok, sync_msg = save_streamrip_settings(
                    streamrip_config_path,
                    use_auth_token=True,
                    email_or_userid=resolved_identifier,
                    password_or_token=str(env_qobuz_token or "").strip(),
                    app_id=str(active_qobuz_app_id or "").strip(),
                    quality=int(streamrip_settings.get("quality", default_rip_quality)),
                    codec_selection=str(streamrip_settings.get("codec_selection", default_codec)),
                    downloads_folder=str(streamrip_settings.get("downloads_folder", "")).strip() or default_downloads_folder,
                    downloads_db_path=str(streamrip_settings.get("downloads_db_path", "")),
                    failed_downloads_path=str(streamrip_settings.get("failed_downloads_path", "")),
                )
                if sync_ok:
                    streamrip_settings, streamrip_settings_error = load_streamrip_settings(streamrip_config_path)
                    _cache_streamrip_runtime_state(
                        streamrip_config_path,
                        streamrip_config_ready,
                        streamrip_config_init_msg,
                        streamrip_settings,
                        streamrip_settings_error,
                        env_qobuz_app_id,
                        env_qobuz_token,
                    )
                    st.session_state.qobuz_autofill_notice = (
                        "Qobuz token was validated in Qobuz Settings and Streamrip was auto-updated "
                        f"(token, App ID, identifier: `{resolved_identifier}`)."
                    )
                    remember_session_snapshot_value("qobuz_autofill_notice", st.session_state.qobuz_autofill_notice)
                    st.success(st.session_state.qobuz_autofill_notice)
                else:
                    _app_debug(f"Qobuz settings token sync to streamrip failed: {sync_msg}")

    account_ok = bool(account_cache.get("ok", False))
    account_data = dict(account_cache.get("data", {}) or {})
    account_msg = str(account_cache.get("message", "")).strip()
    fetched_at = _parse_utc_datetime(str(account_cache.get("fetched_at", "")))
    days_left = _qobuz_account_days_until_expiry(str(account_cache.get("subscription_expires_at", "")))

    st.markdown("### Account Status")
    if not can_fetch_account_info:
        st.caption("Set both token and App ID to fetch account details.")
    elif account_ok:
        if days_left is not None:
            if days_left < 0:
                st.error(f"Subscription appears expired ({abs(days_left)} day(s) ago).")
            elif days_left <= 7:
                st.warning(f"Subscription expires in {days_left} day(s). This check refreshes once per day.")
            else:
                st.success(f"Subscription valid for {days_left} day(s).")
        elif account_msg:
            st.info(account_msg)
    elif account_msg:
        st.warning(account_msg)

    c1, c2 = st.columns(2)
    with c1:
        st.text_input("Identifier", value=str(account_data.get("identifier", "")), disabled=True)
        st.text_input("Email", value=str(account_data.get("email", "")), disabled=True)
        st.text_input("User ID", value=str(account_data.get("user_id", "")), disabled=True)
        st.text_input("Login", value=str(account_data.get("login", "")), disabled=True)
    with c2:
        st.text_input("Country", value=str(account_data.get("country", "")), disabled=True)
        st.text_input("Plan", value=str(account_data.get("subscription_plan", "")), disabled=True)
        st.text_input("Status", value=str(account_data.get("subscription_status", "")), disabled=True)
        st.text_input(
            "Subscription Expires At (UTC)",
            value=str(account_data.get("subscription_expires_at", "")),
            disabled=True,
        )
        st.text_input(
            "Next Renewal (UTC)",
            value=str(account_data.get("next_renewal_at", "")),
            disabled=True,
        )

    if fetched_at is not None:
        st.caption(f"Last account refresh: {fetched_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    st.markdown("---")
    st.caption("Need Streamrip credentials and paths too?")
    if st.button("Open Streamrip Settings Tab", key="qobuz_open_streamrip_tab"):
        st.session_state.main_tab_selection_pending = "Streamrip Settings"
        st.rerun()

if main_tab == "Streamrip Settings":
    st.subheader("⚙️ Streamrip Settings")
    if streamrip_config_init_msg:
        st.info(streamrip_config_init_msg)
    if streamrip_settings_error:
        st.warning(streamrip_settings_error)

    runtime_col1, runtime_col2 = st.columns(2)
    with runtime_col1:
        st.session_state.active_rip_quality = st.selectbox(
            "Rip Quality",
            options=QUALITY_OPTIONS,
            index=QUALITY_OPTIONS.index(st.session_state.active_rip_quality),
            format_func=format_quality_option,
            help="Runtime rip quality used by quick rip actions in tool tabs (equivalent to `--quality`).",
            key="streamrip_runtime_rip_quality",
        )
    with runtime_col2:
        st.session_state.active_rip_codec = st.selectbox(
            "Rip Codec",
            options=CODEC_OPTIONS,
            index=CODEC_OPTIONS.index(st.session_state.active_rip_codec),
            help="Runtime codec used by quick rip actions in tool tabs (equivalent to `--codec`). Use Original for no conversion flag.",
            key="streamrip_runtime_rip_codec",
        )
    st.caption("Qobuz and Tidal ripping requires a premium subscription.")

    render_streamrip_setup(
        streamrip_needs_setup=streamrip_needs_setup,
        streamrip_config_path=streamrip_config_path,
        streamrip_config_ready=streamrip_config_ready,
        streamrip_settings=streamrip_settings,
        default_rip_quality=default_rip_quality,
        default_codec=default_codec,
        env_qobuz_app_id=env_qobuz_app_id,
        env_qobuz_token=env_qobuz_token,
        expanded_override=True,
        key_prefix="shared_streamrip_setup",
        include_browser=True,
        missing_required_fields=streamrip_missing_required_fields,
    )
    if st.session_state.streamrip_setup_attention_message:
        _app_debug(f"Streamrip setup attention warning shown: {st.session_state.streamrip_setup_attention_message}")
        st.warning(st.session_state.streamrip_setup_attention_message)
        st.session_state.streamrip_setup_attention_message = ""
    if st.session_state.streamrip_setup_matcher_scroll_once:
        st.iframe(
            """
            <script>
                const doc = window.parent.document;
                const root = doc.querySelector("section.main");
                if (root) {
                    root.scrollTo({ top: 0, behavior: "smooth" });
                } else {
                    window.parent.scrollTo({ top: 0, behavior: "smooth" });
                }
            </script>
            """,
            height=1,
        )
        st.session_state.streamrip_setup_matcher_scroll_once = False
    st.session_state.streamrip_setup_matcher_expand_once = False

if main_tab == "Bandcamp Matcher":
    if matcher_wip:
        render_wip_notice()
    matcher_requires_env_token = (not dry_run) and (not bool(str(env_qobuz_token).strip()))
    if matcher_requires_env_token:
        st.warning("Actions in this tab are disabled until `QOBUZ_USER_AUTH_TOKEN` is set in `.env` (or enable Dry Run).")
        if st.button("Open Qobuz Settings Tab", key="matcher_open_qobuz_settings"):
            st.session_state.main_tab_selection_pending = "Qobuz Settings"
            st.rerun()
    if streamrip_needs_setup:
        st.warning("Actions in this tab are disabled until Streamrip setup is complete.")
        if st.button("Open Streamrip Settings Tab", key="matcher_top_open_streamrip_settings"):
            if streamrip_missing_required_fields:
                st.session_state.streamrip_setup_focus_field = streamrip_missing_required_fields[0]
            st.session_state.main_tab_selection_pending = "Streamrip Settings"
            st.session_state.streamrip_setup_attention_message = "Finish the missing Streamrip settings to enable ripping."
            st.rerun()

    uploaded_file = st.file_uploader(
        "Upload .txt or .log file with Bandcamp URLs",
        type=["txt", "log"],
        disabled=matcher_wip,
    )

    validation_errors = validate_filters(
        min_tracks,
        max_tracks,
        min_duration,
        max_duration,
        start_date,
        end_date,
    )
    if validation_errors:
        for err in validation_errors:
            st.session_state.auto_scroll_alerts_once = True
            st.error(err)

    filter_config = {
        "tag": tag_input,
        "exclude_tag": exclude_tag_input,
        "location": location_input,
        "min_tracks": int(min_tracks) if min_tracks else None,
        "max_tracks": int(max_tracks) if max_tracks else None,
        "min_duration": int(min_duration) if min_duration else None,
        "max_duration": int(max_duration) if max_duration else None,
        "free_mode": free_mode,
        "check_red": check_red if "check_red" in locals() else False,
        "check_ops": check_ops if "check_ops" in locals() else False,
    }

    col1, col2, col3 = st.columns([1.2, 1.6, 4])
    with col1:
        process_btn = st.button(
            "Process",
            type="primary",
            disabled=matcher_wip or bool(validation_errors) or matcher_requires_env_token,
            help=(
                "Disabled until QOBUZ_USER_AUTH_TOKEN is set in `.env` (unless Dry Run is enabled)."
                if matcher_requires_env_token
                else "Run Bandcamp filtering and Qobuz matching."
            ),
        )
    with col2:
        auto_rip_after_export = st.toggle(
            "Auto rip after export",
            value=False,
            help="Automatically run streamrip after exporting this run's Qobuz results.",
            disabled=matcher_wip,
        )
    with col3:
        stop_btn = st.button(
            "Stop / Cancel",
            help="Stops after the current in-flight batch and shows partial results.",
            disabled=matcher_wip or not st.session_state.processing,
        )

    if stop_btn and st.session_state.processing:
        st.session_state.cancel_requested = True
        st.info("Stop requested. Processing will end after the current batch.")

    handle_process_submission(
        process_btn=process_btn,
        uploaded_file=uploaded_file,
        filter_config=filter_config,
        start_date=start_date,
        end_date=end_date,
        dry_run=dry_run,
    )

    run_processing_tick()
    render_status_log(dry_run=dry_run)
    render_results_and_exports(
        dry_run=dry_run,
        rip_quality=rip_quality,
        rip_codec=rip_codec,
        auto_rip_after_export=auto_rip_after_export,
        streamrip_needs_setup=streamrip_needs_setup,
        streamrip_missing_required_fields=streamrip_missing_required_fields,
    )
elif main_tab == "Direct Qobuz Rip":
    if direct_rip_wip:
        render_wip_notice()
    render_direct_qobuz_rip_tab(
        rip_quality=rip_quality,
        rip_codec=rip_codec,
        streamrip_needs_setup=streamrip_needs_setup,
        streamrip_missing_required_fields=streamrip_missing_required_fields,
        locked=direct_rip_wip,
    )
elif main_tab == "Smoked Salmon Upload":
    render_smoked_salmon_tab(
        default_downloads_folder=default_downloads_folder,
        locked=smoked_salmon_wip,
        show_settings=False,
        show_upload=True,
    )
elif main_tab == "Smoked Salmon Settings":
    render_smoked_salmon_tab(
        default_downloads_folder=default_downloads_folder,
        locked=smoked_salmon_wip,
        show_settings=True,
        show_upload=False,
    )

_render_alert_scroll_if_requested()
